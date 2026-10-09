"""Course source isolation, real LearnMargin rendering, and grounded graph validation."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from learnmargin.demo import demo_lesson
from learnmargin.models import APIConfig, GenerateRequest
from learnmargin.storage import Store
from pliac.margin import materials, run_job
from pliac.margin_graph import ConceptGraph, Vocabulary, VocabularyAudit, Relations, validate_map, overview_map, generate_map
from learning_agent.acceptance_course import build_graph
from learning_agent.course_graph import CourseGraphError


class MaterialTests(unittest.TestCase):
    def test_authored_material_is_complete_and_scoped(self):
        graph = build_graph()
        docs, origins = materials(graph)
        self.assertEqual(10, len(docs[0].units))
        self.assertIn(graph["nodes"][0]["lesson_content"][2]["text"], docs[0].units[0].text)
        self.assertEqual({}, origins)
        chapter, _ = materials(graph, graph["chapters"][0]["id"])
        self.assertEqual(5, len(chapter[0].units))
        self.assertFalse(any("10 最终" in u.label for u in chapter[0].units))
        with self.assertRaises(CourseGraphError): materials(graph, 'missing')

    def test_linked_document_uses_full_original_page_not_short_graph_quote(self):
        graph = build_graph()
        graph['nodes'] = [{**graph['nodes'][0], 'document_id':'a'*32,
                           'document_evidence':[{'page':7,'text':'short quote'}]}]
        documents=SimpleNamespace(status=lambda _: {'title':'已有教材','page_kind':'pdf'},
                                  page=lambda ident,page:{'text':'完整原材料及前提定义，并不是图谱里截取的短句。'})
        docs, origins = materials(graph, documents=documents)
        self.assertEqual(7,docs[0].units[0].index)
        self.assertIn('完整原材料',docs[0].units[0].text)
        self.assertTrue(origins['a'*32+':7']['url'].endswith('#page=7'))

    def test_unrelated_uploaded_material_is_never_loaded(self):
        documents=SimpleNamespace(status=lambda _: self.fail('unrelated source accessed'))
        docs,_=materials(build_graph(),documents=documents)
        self.assertEqual(1,len(docs))

    def test_empty_material_reports_missing_content(self):
        graph=build_graph();graph['nodes']=[]
        with self.assertRaises(CourseGraphError): materials(graph)


class GraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_generated_graph_is_anchored_and_rejects_fabricated_evidence(self):
        lesson=demo_lesson()
        payload={'nodes':[{'id':'p','title':'条件概率','definition':'在已知条件下计算概率',
                  'section_ids':['s1'],'evidence_section':'s1','quote':'已知 $B$ 发生后，只在 $B$ 的范围内考察 $A$。'}], 'edges':[]}
        indexed={'nodes':[{'id':'p','title':'条件概率','definition':'在已知条件下计算概率','section_ids':['s1'],'evidence_id':'p1'}]}
        provider=SimpleNamespace(generate=AsyncMock(side_effect=[Vocabulary.model_validate(indexed),VocabularyAudit(decisions=[{'id':'p','atomic':True,'domain_term':True,'reason':'可独立定义的概率概念'}]),Relations(edges=[])]))
        graph=await generate_map(lesson,provider)
        self.assertEqual(['example:1'],graph['nodes'][0]['source_refs'])
        self.assertEqual(3,provider.generate.await_count)
        bad=copy.deepcopy(payload);bad['nodes'][0]['quote']='这里并没有的原文内容。'
        with self.assertRaises(ValueError): validate_map(ConceptGraph.model_validate(bad),lesson)
        bad=copy.deepcopy(payload);bad['nodes'][0]['section_ids']=['missing']
        with self.assertRaises(ValueError): validate_map(ConceptGraph.model_validate(bad),lesson)

    async def test_concept_gate_rejects_instructions_across_unrelated_subjects(self):
        for title, text in [('电场','电场是描述电荷间相互作用的物理场。先画示意图，然后理解场与电荷的关系。此段作为独立物理材料。'),
                            ('递归','递归是函数调用自身来分解问题的方法。先画示意图，然后检查基例与递推步骤。此段作为独立程序设计材料。')]:
            lesson=demo_lesson().model_copy(deep=True)
            lesson.sections=lesson.sections[:1]
            lesson.sections[0].title=title
            lesson.sections[0].explanation=text
            nodes=[{'id':'term','title':title,'definition':text,'section_ids':['s1'],'evidence_id':'p1'},
                   {'id':'instruction','title':'先画示意图','definition':'阅读动作','section_ids':['s1'],'evidence_id':'p1'}]
            provider=SimpleNamespace(generate=AsyncMock(side_effect=[Vocabulary(nodes=nodes),
                VocabularyAudit(decisions=[{'id':'term','atomic':True,'domain_term':True,'reason':'学科术语'},
                                           {'id':'instruction','atomic':False,'domain_term':False,'reason':'操作指令不是概念'}]),Relations(edges=[])]))
            result=await generate_map(lesson,provider)
            self.assertEqual(['term'],[n['id'] for n in result['nodes']])
            allowed=provider.generate.await_args_list[-1].args[2].split('已审核术语：')[1]
            self.assertNotIn('"id": "instruction"',allowed)
            self.assertEqual('concept-first-v2',result['policy_version'])

    async def test_real_renderer_delivers_pdf_and_graph_from_course_snapshot(self):
        lesson=demo_lesson()
        docs,origins=materials(build_graph())
        class ProviderStub:
            usage=[]
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp));job={'id':'b'*32,'status':'queued','created_at':'2026-10-09','course_id':'ml_acceptance_demo','course_version':1}
            store.save_job(job)
            request=GenerateRequest(document_ids=[docs[0].id],api=APIConfig(base_url='http://127.0.0.1',model='test'))
            with patch('pliac.margin.Provider',return_value=ProviderStub()),patch('pliac.margin.generate_lesson',new=AsyncMock(return_value=lesson)) as writer,patch('pliac.margin.generate_map',new=AsyncMock(return_value=overview_map(lesson))):
                await run_job(store,job,request,docs,origins)
            self.assertEqual('completed',job['status'],job.get('error'))
            writer.assert_awaited_once()
            folder=store.directory('jobs',job['id'])
            self.assertTrue((folder/'lesson.pdf').read_bytes().startswith(b'%PDF'))
            self.assertIn('条件概率',(folder/'lesson.html').read_text(encoding='utf-8'))
            snapshot=json.loads((folder/'materials.json').read_text(encoding='utf-8'))
            self.assertEqual(10,len(snapshot['documents'][0]['units']))
            self.assertTrue((folder/'knowledge-map.json').is_file())
            self.assertNotIn('api_key',(folder/'generation.json').read_text(encoding='utf-8'))

if __name__=='__main__': unittest.main()
