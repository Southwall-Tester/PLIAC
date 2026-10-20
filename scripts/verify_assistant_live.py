"""Two synthetic tutoring turns against the configured model; isolated profile."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from learning_agent import api
from learning_agent.course_graph import CourseGraphStore
from pliac.assistant import ChatProvider
from pliac.assistant_context import clean_context, context_for
from pliac.margin import configured_api
from pliac import assistant_profile as profiles
from build_linux_course import DEST, COURSE_ID
from install_course_draft import install


async def main():
    config = configured_api().model_copy(update={"timeout_seconds": 90})
    records, messages = [], []
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        store = CourseGraphStore(output_dir=folder/"store")
        install(DEST/"course.json", store)
        with patch.object(api, "store", store):
            for question in [
                "我喜欢先给结论再举例。我认为执行 ls /tmp 后当前目录就变成 /tmp，这个理解对吗？",
                "我修正一下：ls 只是列出内容，当前目录仍是 /home/lin，相对路径 notes 指向 /home/lin/notes，因为没有运行 cd。我这样解释对吗？",
            ]:
                user = dict(id=uuid.uuid4().hex, role="user", content=question)
                messages.append({"role":"user", "content":question})
                context = context_for(clean_context(dict(course_id=COURSE_ID, node_id="cwd")), question)
                profile = profiles.load(folder)
                context["personalization"] = profiles.relevant(profile, question, COURSE_ID)
                async with ChatProvider(config) as provider:
                    result = await provider.chat(messages, context)
                diagnoses, accepted = profiles.apply(folder, result, user, context, "synthetic-live", profile["revision"])
                records.append(dict(question=question, reply=result.model_dump(), accepted_diagnosis=diagnoses,
                                    accepted_memory_ids=accepted, applied_profile=context["personalization"]))
                messages.append({"role":"assistant", "content":result.answer})
                print(f"Turn {len(records)}: signals={[d['signal'] for d in diagnoses]}, memories={len(accepted)}", flush=True)
    checks = dict(
        identifies_misconception=any(d["signal"]=="misconception" for d in records[0]["accepted_diagnosis"]),
        recognizes_corrected_explanation=any(d["signal"]=="correct" for d in records[1]["accepted_diagnosis"]),
        preference_reused=bool(records[1]["applied_profile"]["preferences"]),
        prior_diagnosis_reused=bool(records[1]["applied_profile"]["learning_focus"]),
    )
    output=ROOT/"outputs/verification/assistant/live-model.json"
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(model=config.model, synthetic=True, checks=checks, records=records),
                                ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False))
    if not all(checks.values()):
        raise SystemExit("Live synthetic scenario needs review; see " + str(output))


if __name__ == "__main__":
    asyncio.run(main())
