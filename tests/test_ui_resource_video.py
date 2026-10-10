"""Real video decode and bookmark API; synthetic blank video, no external fetch."""
import subprocess
import re
import tempfile
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from test_ui_documents import isolated_application
from test_course_graph import fixture
from test_learning_workspace import publish_synthetic


def main():
    with tempfile.TemporaryDirectory() as folder, isolated_application(Path(folder)) as (base, store, _), sync_playwright() as p:
        clip = Path(folder) / 'synthetic.webm'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=white:s=320x180:r=10', '-t', '3', '-c:v', 'libvpx', str(clip)], check=True, capture_output=True, timeout=30)
        graph = fixture(); graph['version'] = store.load_graph('draft')['version']
        graph['resources'][0].update(format='video', url='https://media.example.test/synthetic.webm', video_segment={'start_seconds': 1, 'end_seconds': 2})
        publish_synthetic(store, graph)
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        page.add_init_script("localStorage.setItem('pliac.local-learner', 'synthetic-video')")
        requests = []
        def media(route):
            requests.append(route.request.url)
            content = clip.read_bytes()
            headers = {'Access-Control-Allow-Origin': '*', 'Accept-Ranges': 'bytes'}
            requested = re.fullmatch(r'bytes=(\d+)-(\d*)', route.request.headers.get('range', ''))
            if requested:
                start = int(requested[1]); end = min(int(requested[2]) if requested[2] else len(content) - 1, len(content) - 1)
                headers['Content-Range'] = f'bytes {start}-{end}/{len(content)}'
                route.fulfill(status=206, body=content[start:end + 1], content_type='video/webm', headers=headers)
            else:
                route.fulfill(body=content, content_type='video/webm', headers=headers)
        page.route('https://media.example.test/**', media)
        page.goto(base + '/app/courses/' + graph['id'])
        page.get_by_role('button', name='选择学习材料', exact=True).click()
        expect(page.get_by_role('button', name='在工作台播放视频')).to_be_visible()
        assert not requests
        page.get_by_role('button', name='在工作台播放视频').click()
        page.wait_for_function("document.querySelector('video')?.readyState >= 1")
        expect(page.locator('video')).to_be_focused()
        page.locator('video').evaluate('(el)=>{window.closedVideo=el;}')
        page.get_by_role('button', name='关闭视频', exact=True).click()
        expect(page.get_by_role('button', name='在工作台播放视频')).to_be_focused()
        assert page.evaluate('window.closedVideo.paused && !window.closedVideo.hasAttribute("src")')
        page.get_by_role('button', name='在工作台播放视频').click()
        page.wait_for_function("document.querySelector('video')?.readyState >= 1")
        assert page.locator('video').evaluate('(el)=>el.paused')
        page.get_by_role('button', name='定位推荐片段').click()
        page.wait_for_function("document.querySelector('video').currentTime >= .9 && document.querySelector('video').paused && !document.querySelector('video').seeking")
        expect(page.get_by_role('status')).to_contain_text('推荐起点 1 秒')
        page.locator('video').evaluate('(el)=>{el.currentTime=1; window.testVideo=el;}')
        page.wait_for_function("document.querySelector('video').currentTime >= .9 && !document.querySelector('video').seeking")
        page.get_by_role('button', name='保存视频位置').click()
        expect(page.get_by_role('status')).to_contain_text('播放位置已保存到学习档案')
        page.get_by_role('button', name='关闭材料选择').click()
        assert page.evaluate('window.testVideo.paused && !window.testVideo.hasAttribute("src")')
        page.goto(base + '/app/')
        page.get_by_role('region', name='继续学习').get_by_role('link').filter(has_text=graph['resources'][0]['title']).click()
        expect(page.get_by_role('dialog', name='选择学习材料')).to_be_visible()
        page.get_by_role('button', name='在工作台播放视频').click()
        page.get_by_role('button', name='恢复视频位置').click()
        expect(page.get_by_role('status')).to_contain_text('已定位到保存时间')
        page.wait_for_function("document.querySelector('video').currentTime >= .9 && document.querySelector('video').paused && !document.querySelector('video').seeking")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        changed = store.load_graph('draft')
        changed['resources'][0]['video_segment']['end_seconds'] = 4
        publish_synthetic(store, changed)
        page.reload()
        expect(page.get_by_role('dialog', name='选择学习材料')).to_be_visible()
        page.get_by_role('button', name='在工作台播放视频').click()
        page.get_by_role('button', name='定位推荐片段').click()
        expect(page.get_by_role('status')).to_contain_text('推荐片段超出当前视频时长')
        assert page.locator('video').evaluate('(el)=>el.paused')
        browser.close()
    print('PASS explicit video load, actual decode, server bookmark, reload restore and close cleanup; synthetic clip only')


if __name__ == '__main__': main()
