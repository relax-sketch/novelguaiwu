from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from library.db import LibraryDB, WorkFilter
from library.scanner import ScanSettings, browser_program as scanner_browser_program, load_fixture, normalize_works
from library.app import FORUM_TAG_PRESETS, PAGE, RETRYABLE_DOWNLOAD_STATUSES, _is_client_disconnect
from library.purchase import SKIP_PURCHASE_TAGS, PurchaseCandidate, browser_program
from library.cleaner import clean_posts, clean_text
from library.content import clean_filename, save_snapshot
from library.content_browser import browser_program as content_browser_program
from library.downloader import DownloadSettings, build_download_queue, plan_download
from library.exporter import export_txt, export_zip
from library.updater import posts_changed, resolve_download_status, work_changed
from library.automation_browser import BrowserConfig


class LibraryDBTests(unittest.TestCase):
    def test_upsert_filter_and_update_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp, LibraryDB(Path(temp) / "library.sqlite3") as db:
            settings = ScanSettings(pages=1)
            items = normalize_works(load_fixture(Path(__file__).parents[1] / "fixtures" / "library_sample.json", settings), settings)
            self.assertEqual(db.upsert_many(items, sort_type="views"), 3)
            self.assertEqual([x["name"] for x in db.list_authors()], ["作者丙", "作者乙", "作者甲"])
            db.connection.execute("UPDATE works SET download_status='已下载' WHERE thread_id='1001'"); db.connection.commit()
            changed = dict(items[0]); changed["replies"] = 174; db.upsert_many([changed], sort_type="views")
            self.assertEqual([x["thread_id"] for x in db.list_works({"status":"已下载"})], ["1001"])
            self.assertEqual(len(db.list_works(WorkFilter(include_tags=["女主视角"]))), 1)
            self.assertEqual(len(db.list_works({"exclude_tags":"催眠NTR"})), 2)
            changed["price"] = 0
            db.update_purchase_result("1001", status="已购买", price=2)
            db.upsert_many([changed], sort_type="views")
            self.assertEqual(db.list_works()[0]["price"], 2)
            db.update_purchase_result("1002", status="已购买或免费")
            self.assertEqual(db.list_works()[1]["purchase_status"], "免费")
            db.upsert_many([dict(items[1], price=0)], sort_type="views")
            self.assertEqual(db.list_works()[1]["purchase_status"], "免费")
            db.update_download_result("1002", status="购买失败", purchase_status="购买失败")
            failed = next(row for row in db.list_works() if row["thread_id"] == "1002")
            self.assertEqual(failed["download_status"], "下载失败")
            db.upsert_post({"thread_id":"1002","remote_post_id":"old","floor_number":1,"raw_html":"旧"})
            db.replace_posts("1002", [{"thread_id":"1002","remote_post_id":"new","floor_number":1,"raw_html":"新"}])
            self.assertEqual([p["remote_post_id"] for p in db.list_posts("1002")], ["new"])
            self.assertEqual(failed["purchase_status"], "购买失败")

    def test_run_config_and_page_tag_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp, LibraryDB(Path(temp) / "library.sqlite3") as db:
            run_id = db.start_run("views", {"pages": 20, "forum_url": "fid=3"})
            db.finish_run(run_id, scanned_count=4, stop_reason="正常完成", results=[{"thread_id":"1001","status":"页面异常","reason":"测试原因"}])
            row = db.connection.execute("SELECT filter_config, scanned_count, finished_at FROM runs WHERE id=?", (run_id,)).fetchone()
            self.assertIn('"pages": 20', row["filter_config"])
            self.assertEqual(row["scanned_count"], 4)
            self.assertTrue(row["finished_at"])
            self.assertEqual(db.list_runs(limit=1)[0]["filter_config"]["pages"], 20)
            self.assertEqual(db.list_runs(limit=1)[0]["results"][0]["reason"], "测试原因")
            self.assertIn("include_tag_picker", PAGE)
            self.assertIn("include_tag_select", PAGE)
            self.assertIn("exclude_tag_select", PAGE)
            self.assertEqual(len(FORUM_TAG_PRESETS), 17)
            self.assertIn("/api/tags", PAGE)
            self.assertIn("购买设置", PAGE)
            self.assertIn("/api/purchase", PAGE)
            self.assertIn("预设标签", PAGE)
            self.assertIn("未探测", PAGE)
            self.assertIn("/api/download", PAGE)
            self.assertIn("/api/export", PAGE)
            self.assertIn("下载当前筛选结果", PAGE)
            self.assertIn("导出当前筛选结果", PAGE)
            self.assertIn("title_keyword", PAGE)
            self.assertIn("download_execute", PAGE)
            self.assertIn('<section class="card purchase-card" hidden>', PAGE)
            self.assertIn("本次下载篇数", PAGE)
            self.assertIn("download_max_price", PAGE)
            self.assertIn("download_min_balance", PAGE)
            self.assertIn("download_max_pages", PAGE)
            self.assertIn("单帖最多页数", PAGE)
            self.assertIn("单帖最多抓取", PAGE)
            self.assertIn("library.max_pages_per_work", PAGE)
            self.assertIn("downloadPosts('auto')", PAGE)
            self.assertIn("/api/authors", PAGE)
            self.assertIn("全部作者", PAGE)
            self.assertIn("execute=true", PAGE)
            self.assertIn("run-detail", PAGE)
            self.assertIn("重新抓取勾选正文", PAGE)
            self.assertIn("重试所有失败", PAGE)
            self.assertIn("downloadPosts('retry_failed')", PAGE)
            self.assertIn('downloadPosts(\'redownload\')', PAGE)
            self.assertIn('onclick="pickRange(event,${i})"', PAGE)
            self.assertIn('按住 Shift 可连续选择', PAGE)

    def test_client_disconnect_is_not_a_task_failure(self) -> None:
        self.assertTrue(_is_client_disconnect(ConnectionAbortedError(10053)))
        self.assertTrue(_is_client_disconnect(ConnectionResetError(10054)))
        self.assertTrue(_is_client_disconnect(BrokenPipeError()))
        self.assertFalse(_is_client_disconnect(RuntimeError("browser failed")))
        self.assertEqual(RETRYABLE_DOWNLOAD_STATUSES, {"下载失败", "购买失败", "页面异常", "余额不足", "金币超限"})

    def test_purchase_program_is_dry_run_by_default(self) -> None:
        script = browser_program([PurchaseCandidate("802", "https://example.test/thread/802")], max_price=3, execute=False, count=2)
        compile(script, "<purchase-browser>", "exec")
        self.assertIn('"execute": false', script)
        self.assertIn('"count": 2', script)
        self.assertIn("if _bought >= int(_cfg['count']): break", script)
        self.assertIn("待购买", script)
        self.assertIn("版务", SKIP_PURCHASE_TAGS)
        auto_script = browser_program([], max_price=3, execute=False, count=100, auto_purchase=True, min_balance=20)
        self.assertIn('"auto_purchase": true', auto_script)
        self.assertIn('"min_balance": 20', auto_script)
        self.assertIn("余额保留", auto_script)
        self.assertNotIn("for poll in range(1,4)", script)
        self.assertIn("for delay in (0.75,1.5,2.25)", script)
        self.assertIn("_time.sleep(2)", script)
        self.assertNotIn("range(1,5)", script)
        self.assertIn("_verify_purchase", script)
        self.assertIn("主题购买成功", script)
        self.assertIn("except Exception: pass", script)
        self.assertIn("browser_result", script)
        self.assertIn("wait_for_network_idle_error", script)
        self.assertIn("pay_navigation_error", script)
        self.assertIn("state,thread_attempts=_load_thread(item['url'])", script)
        self.assertIn("已重试3次", script)
        self.assertNotIn("capture_screenshot()", script)
        content_script = content_browser_program([{"thread_id":"1","url":"https://example.test"}], execute=False, min_balance=20, download_limit=3, max_pages_per_work=6)
        compile(content_script, "<content-browser>", "exec")
        self.assertIn("querySelectorAll('img').forEach", content_script)
        self.assertIn("p['author_id']==author_id", content_script)
        self.assertIn("余额不足", content_script)
        self.assertIn("页面异常", content_script)
        self.assertIn("# purchase_status 只是数据库缓存；主题页当前 DOM 才是实时状态。", content_script)
        self.assertIn("if state['buy']:", content_script)
        self.assertIn("elif state.get('body_nodes', 0) > 0:", content_script)
        self.assertIn("purchase_status='已购买' if detected_price > 0 else '免费'", content_script)
        self.assertIn("主题页既无购买入口也无正文", content_script)
        self.assertNotIn("purchase_status not in ('已购买','免费')", content_script)
        self.assertNotIn("item.get('purchase_status')", content_script)
        self.assertIn('"min_balance": 20', content_script)
        self.assertIn('"download_limit": 3', content_script)
        self.assertIn('"max_pages_per_work": 6', content_script)
        self.assertIn("effective_page_count=min", content_script)
        self.assertIn("'page_limit_applied'", content_script)
        self.assertIn("wait_for_element('#payform'", content_script)
        self.assertIn("_verify_purchase", content_script)
        self.assertIn("主题购买成功", content_script)
        self.assertIn("except Exception: pass", content_script)
        self.assertIn("browser_result", content_script)
        self.assertIn("wait_for_network_idle_error", content_script)
        self.assertIn("pay_navigation_error", content_script)
        self.assertIn("state,thread_attempts=_load_thread(item['url'], settle=True)", content_script)
        self.assertIn("已重试3次", content_script)
        self.assertIn("for delay in (0.75,1.5,2.25)", content_script)
        self.assertIn("_load_thread(item['url'], settle=True)", content_script)
        self.assertIn("settle=False", content_script)
        self.assertIn("_time.sleep(2); state=_state()", content_script)
        self.assertNotIn("capture_screenshot()", content_script)

    def test_scanner_and_purchase_state_contract(self) -> None:
        scan_script = scanner_browser_program(ScanSettings(pages=1))
        compile(scan_script, "<scan-browser>", "exec")
        self.assertIn("const priceMatch = text.match(/售价\\s*(\\d+)\\s*金钱/)", scan_script)
        self.assertIn("price:price", scan_script)

        purchase_script = browser_program([], max_price=3, execute=False)
        self.assertNotIn("known_status", purchase_script)
        self.assertIn("state.get('body_nodes', 0) and price > 0", purchase_script)
        self.assertIn("state.get('body_nodes', 0) else '购买状态未确认'", purchase_script)

    def test_automation_browser_is_isolated_and_visible_without_images(self) -> None:
        config = BrowserConfig.from_env()
        self.assertFalse(config.headless)
        self.assertTrue(config.no_images)
        env = config.child_env({"PATH": "test-path"})
        self.assertEqual(env["BU_CDP_URL"], config.cdp_url)
        self.assertEqual(env["BU_NAME"], config.daemon_name)
        self.assertEqual(env["BH_HOME"], str(config.harness_home))
        self.assertNotEqual(config.profile_root, Path(__file__).parents[1] / ".venv")

    def test_clean_save_export_and_queue(self) -> None:
        self.assertEqual(clean_text('<p>正文</p><blockquote>不要保留</blockquote><p>第二段</p>'), "正文\n\n第二段")
        posts, digest = clean_posts([{"floor_number": 1, "raw_html": "<p>正文</p>"}, {"floor_number": 2, "raw_html": "谢谢支持"}], minimum_length=200)
        self.assertEqual(posts[1]["post_type"], "作者短回复"); self.assertTrue(digest)
        with tempfile.TemporaryDirectory() as temp:
            info = save_snapshot(temp, {"thread_id":"1","title":"测试","author_name":"作者"}, [{"floor_number":1,"raw_html":"<p>正文</p>"}])
            self.assertTrue(Path(info["clean_path"]).exists())
            self.assertEqual(clean_filename("作者", "测试"), "测试_作者.txt")
            txt = export_txt([info["local_path"]], Path(temp) / "out.txt"); zip_path = export_zip([info["local_path"]], Path(temp) / "out.zip")
            self.assertIn("正文", txt.read_text(encoding="utf-8")); self.assertTrue(zip_path.exists())
        rows = [{"thread_id":"1","download_status":"未下载","tags":["改造变化"]},{"thread_id":"2","download_status":"未下载","tags":["版务"]},{"thread_id":"3","download_status":"有更新","local_path":"data/done","tags":[]}]
        self.assertEqual([x["thread_id"] for x in build_download_queue(rows)], ["1"])
        self.assertEqual([x["thread_id"] for x in build_download_queue(rows, force=True)], ["1", "2", "3"])
        preview = plan_download(rows, DownloadSettings(count=1))
        self.assertEqual(preview[0]["thread_id"], "1")
        self.assertEqual(preview[0]["status"], "待下载")
        self.assertEqual(build_download_queue([{"thread_id":"4","download_status":"已下载","tags":[]}]), [])

    def test_update_detection(self) -> None:
        self.assertTrue(work_changed({"replies": 1, "last_reply_time": "a", "page_count": 1}, {"replies": 2, "last_reply_time": "a", "page_count": 1}))
        self.assertTrue(posts_changed([{"remote_post_id":"1","content_hash":"a"}], [{"remote_post_id":"1","content_hash":"b"}]))
        self.assertEqual(resolve_download_status(was_downloaded=True, content_changed=False), "已下载")


if __name__ == "__main__": unittest.main()
