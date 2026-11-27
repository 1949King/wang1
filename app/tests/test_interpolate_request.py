"""app/tests/test_interpolate_request.py — 补帧请求解析契约（T4 项二，2026-11-20）。

parse_interpolate_request 是纯函数（不触网、不读视频、不依赖 torch）：
  1. multiplier 钳制到 [2,4]，默认 2；0/1⇒2、9⇒4、非数⇒2、"3"⇒3、2.9⇒2。
  2. 视频源 video_url / video_path（含 camelCase）二选一；空 body / 非 dict ⇒ error。
  3. legacy mode / target_fps / title 透传（target_fps 默认 24）。
"""
from app.core.video_interpolate_job import parse_interpolate_request


class TestMultiplierClamp:
    """multiplier 钳制与容错。"""

    def test_default_is_two(self):
        req = parse_interpolate_request({"video_url": "/inbox_file/a.mp4"})
        assert req["ok"] is True
        assert req["multiplier"] == 2

    def test_zero_clamps_to_two(self):
        req = parse_interpolate_request({"video_url": "a", "multiplier": 0})
        assert req["multiplier"] == 2

    def test_one_clamps_to_two(self):
        req = parse_interpolate_request({"video_url": "a", "multiplier": 1})
        assert req["multiplier"] == 2

    def test_nine_clamps_to_four(self):
        req = parse_interpolate_request({"video_url": "a", "multiplier": 9})
        assert req["multiplier"] == 4

    def test_three_kept(self):
        req = parse_interpolate_request({"video_url": "a", "multiplier": 3})
        assert req["multiplier"] == 3

    def test_non_number_defaults_two(self):
        req = parse_interpolate_request({"video_url": "a", "multiplier": "abc"})
        assert req["multiplier"] == 2

    def test_none_defaults_two(self):
        req = parse_interpolate_request({"video_url": "a", "multiplier": None})
        assert req["multiplier"] == 2

    def test_numeric_string_parsed(self):
        req = parse_interpolate_request({"video_url": "a", "multiplier": "3"})
        assert req["multiplier"] == 3

    def test_float_truncated(self):
        req = parse_interpolate_request({"video_url": "a", "multiplier": 2.9})
        assert req["multiplier"] == 2


class TestVideoSource:
    """视频源校验。"""

    def test_empty_body_error(self):
        req = parse_interpolate_request({})
        assert req["ok"] is False
        assert req.get("error")

    def test_non_dict_error(self):
        assert parse_interpolate_request(None)["ok"] is False
        assert parse_interpolate_request("x")["ok"] is False

    def test_video_url_ok(self):
        req = parse_interpolate_request({"video_url": "/inbox_file/a.mp4"})
        assert req["ok"] is True
        assert req["video_url"] == "/inbox_file/a.mp4"

    def test_video_path_ok(self):
        req = parse_interpolate_request({"video_path": "/tmp/a.mp4"})
        assert req["ok"] is True
        assert req["video_path"] == "/tmp/a.mp4"

    def test_camel_case_url(self):
        req = parse_interpolate_request({"videoUrl": "/inbox_file/a.mp4"})
        assert req["ok"] is True
        assert req["video_url"] == "/inbox_file/a.mp4"


class TestLegacyPassthrough:
    """legacy 字段透传（不驱动实际补帧，仅兼容旧前端）。"""

    def test_mode_passthrough(self):
        req = parse_interpolate_request({"video_url": "a", "mode": "flow"})
        assert req["mode"] == "flow"

    def test_mode_default_smart(self):
        req = parse_interpolate_request({"video_url": "a"})
        assert req["mode"] == "smart"

    def test_target_fps_default(self):
        req = parse_interpolate_request({"video_url": "a"})
        assert req["target_fps"] == 24

    def test_target_fps_parsed(self):
        req = parse_interpolate_request({"video_url": "a", "target_fps": "30"})
        assert req["target_fps"] == 30

    def test_title_passthrough(self):
        req = parse_interpolate_request({"video_url": "a", "title": "镜头1"})
        assert req["title"] == "镜头1"
