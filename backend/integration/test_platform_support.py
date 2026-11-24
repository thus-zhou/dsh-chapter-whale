"""E02：Linux 目标平台归一架构、主机匹配与归档校验。"""
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from integration import platform_support as ps


def _archive(root, name, members):
    path = root / name
    with tarfile.open(path, mode="w:gz") as tar:
        for member, data in members.items():
            payload = data.encode("utf-8") if isinstance(data, str) else data
            info = tarfile.TarInfo(member)
            info.size = len(payload)
            info.mtime = 0
            tar.addfile(info, __import__("io").BytesIO(payload))
    return path


MANIFEST = {"schema": 1, "version": "0.9.3", "platform": "linux-arm64", "arch": "arm64",
            "files": 3, "sha256": "a" * 64}


class ManifestTest(unittest.TestCase):
    def test_manifest_matches_target(self):
        result = ps.verify_manifest(MANIFEST, expect_target="linux-arm64",
                                    archive_name="dsh-chapter-whale-service-linux-arm64-0.9.3.tar.gz")
        self.assertTrue(result["ok"], result["problems"])

    def test_manifest_mismatch_and_missing_fields(self):
        self.assertIn("platform_mismatch:linux-arm64!=linux-amd64",
                      ps.verify_manifest(MANIFEST, expect_target="linux-amd64")["problems"])
        self.assertIn("manifest_missing_field:platform", ps.verify_manifest({})["problems"])
        self.assertIn("unknown_platform:linux-riscv",
                      ps.verify_manifest({"platform": "linux-riscv"})["problems"])
        self.assertIn("arch_mismatch:amd64!=arm64",
                      ps.verify_manifest({"platform": "linux-arm64", "arch": "amd64"})["problems"])
        self.assertIn("archive_name_arch_mismatch:wrong.tgz",
                      ps.verify_manifest(MANIFEST, archive_name="wrong.tgz")["problems"])

    def test_arch_is_required_not_defaulted(self):
        missing = dict(MANIFEST)
        missing.pop("arch")
        problems = ps.verify_manifest(missing, expect_target="linux-arm64")["problems"]
        self.assertIn("manifest_missing_field:arch", problems)


class ArchiveTest(unittest.TestCase):
    PAYLOAD = {
        "backend/integration/resident_service.py": "print('ok')\n",
        "deploy/linux/entrypoint.sh": "#!/bin/sh\nexec python -m integration.resident_service start\n",
        "README.md": "# 说明\n",
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def manifest_for(self, payload, platform="linux-arm64", arch="arm64"):
        files, digest = ps._payload_digest(payload)
        return {"schema": 1, "version": "0.9.3", "platform": platform, "arch": arch,
                "files": len(files), "sha256": digest}

    def build(self, name="dsh-chapter-whale-service-linux-arm64-0.9.3.tar.gz",
              manifest=None, manifest_name="service-build.json", **overrides):
        payload = dict(self.PAYLOAD)
        payload.update(overrides)
        manifest = self.manifest_for(payload) if manifest is None else manifest
        members = {manifest_name: json.dumps(manifest)}
        members.update(payload)
        return _archive(self.root, name, members)

    def test_clean_archive_passes(self):
        result = ps.verify_archive(self.build(), expect_target="linux-arm64")
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["files"], 4)
        self.assertEqual(result["payload_files"], 3)
        self.assertEqual(result["target"], "linux-arm64")

    def test_wrong_arch_is_refused(self):
        result = ps.verify_archive(self.build(), expect_target="linux-amd64")
        self.assertFalse(result["ok"])
        self.assertTrue(any(item.startswith("platform_mismatch") for item in result["problems"]))

    def test_renamed_archive_does_not_pass(self):
        result = ps.verify_archive(self.build(name="service-arm64.tar.gz"))
        self.assertFalse(result["ok"])
        self.assertTrue(any(item.startswith("archive_name_arch_mismatch")
                            for item in result["problems"]))

    def test_tampered_payload_is_refused(self):
        good = self.build()
        manifest = self.manifest_for(self.PAYLOAD)
        tampered = self.build(name="tampered-arm64.tar.gz", manifest=manifest,
                              **{"backend/integration/resident_service.py": "print('evil')\n"})
        self.assertTrue(ps.verify_archive(good)["ok"])
        problems = ps.verify_archive(tampered)["problems"]
        self.assertTrue(any(item.startswith("payload_digest_mismatch") for item in problems),
                        problems)

    def test_file_count_mismatch_is_refused(self):
        manifest = self.manifest_for(self.PAYLOAD)
        manifest["files"] = 99
        problems = ps.verify_archive(self.build(manifest=manifest))["problems"]
        self.assertTrue(any(item.startswith("file_count_mismatch") for item in problems),
                        problems)

    def test_windows_binary_inside_is_refused(self):
        result = ps.verify_archive(self.build(**{"vendor/bin/ffmpeg.exe": b"MZ\x90\x00"}))
        self.assertFalse(result["ok"])
        self.assertTrue(any(item.startswith("foreign_binary") for item in result["problems"]))

    def test_crlf_script_is_refused_even_with_nul(self):
        result = ps.verify_archive(self.build(
            **{"deploy/linux/entrypoint.sh": b"#!/bin/sh\r\n\x00exit 0\r\n"}))
        self.assertFalse(result["ok"])
        self.assertTrue(any(item.startswith("crlf") for item in result["problems"]))

    def test_missing_manifest_is_refused(self):
        without = _archive(self.root, "no-manifest-arm64.tar.gz",
                           {"backend/integration/resident_service.py": "print('ok')\n"})
        problems = ps.verify_archive(without)["problems"]
        self.assertTrue(any(item.startswith("manifest_count:0") for item in problems), problems)

    def test_nested_manifest_is_refused(self):
        nested = self.build(manifest_name="deploy/linux/service-build.json")
        problems = ps.verify_archive(nested)["problems"]
        self.assertTrue(any(item.startswith("manifest_not_at_root") for item in problems), problems)

    def test_duplicate_member_is_refused(self):
        path = self.root / "dup-arm64.tar.gz"
        payload = dict(self.PAYLOAD)
        manifest = self.manifest_for(payload)
        with tarfile.open(path, mode="w:gz") as tar:
            for name, data in [("service-build.json", json.dumps(manifest)),
                               *payload.items(),
                               ("README.md", "# 第二份\n")]:
                body = data.encode("utf-8") if isinstance(data, str) else data
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tar.addfile(info, __import__("io").BytesIO(body))
        problems = ps.verify_archive(path)["problems"]
        self.assertTrue(any(item.startswith("duplicate_member") for item in problems), problems)

    def test_linux_elf_machine_must_match_target(self):
        native = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 10 + (0x3E).to_bytes(2, "little")
        foreign = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 10 + (0xB7).to_bytes(2, "little")
        name = "dsh-chapter-whale-service-linux-amd64-0.9.3.tar.gz"
        for payload, want_ok in ((native, True), (foreign, False)):
            merged = dict(self.PAYLOAD)
            merged["vendor/bin/runtime"] = payload
            manifest = self.manifest_for(merged, platform="linux-amd64", arch="amd64")
            path = self.build(name=name, manifest=manifest, **merged)
            result = ps.verify_archive(path, expect_target="linux-amd64")
            self.assertEqual(result["ok"], want_ok, result["problems"])
            if not want_ok:
                self.assertTrue(any(item.startswith("elf_arch_mismatch")
                                    for item in result["problems"]), result["problems"])

    def test_link_and_unsafe_members_are_refused(self):
        import io
        import tarfile

        path = self.root / "dsh-chapter-whale-service-linux-amd64-0.9.3.tar.gz"
        manifest = self.manifest_for(self.PAYLOAD, platform="linux-amd64", arch="amd64")
        with tarfile.open(path, "w:gz") as tar:
            for name, data in self.PAYLOAD.items():
                body = data.encode("utf-8") if isinstance(data, str) else data
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
            body = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
            info = tarfile.TarInfo("service-build.json")
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
            link = tarfile.TarInfo("backend/integration/libcrypto.so.3")
            link.type = tarfile.SYMTYPE
            link.linkname = "/usr/lib/x86_64-linux-gnu/libcrypto.so.3"
            tar.addfile(link)
            escape = tarfile.TarInfo("../../escape.py")
            escape.size = 1
            tar.addfile(escape, io.BytesIO(b"x"))
        problems = ps.verify_archive(path, expect_target="linux-amd64")["problems"]
        self.assertTrue(any(item.startswith("link_member") for item in problems), problems)
        self.assertTrue(any(item.startswith("unsafe_path") for item in problems), problems)

    def test_files_field_must_be_an_integer(self):
        manifest = self.manifest_for(self.PAYLOAD, platform="linux-arm64", arch="arm64")
        manifest["files"] = "2"
        path = self.build(name="dsh-chapter-whale-service-linux-arm64-0.9.3.tar.gz",
                          manifest=manifest, **self.PAYLOAD)
        problems = ps.verify_archive(path, expect_target="linux-arm64")["problems"]
        self.assertIn("manifest_field_type:files", problems)

    def test_corrupt_archive_returns_a_report(self):
        path = self.root / "broken-arm64.tar.gz"
        path.write_bytes(b"not a gzip at all")
        result = ps.verify_archive(path)
        self.assertFalse(result["ok"])
        self.assertTrue(any(item.startswith("archive_unreadable") for item in result["problems"]))

    def test_missing_file_is_an_error(self):
        with self.assertRaises(ps.TargetError):
            ps.verify_archive(self.root / "nope.tar.gz")
class HostMatchTest(unittest.TestCase):
    def test_same_arch_on_linux_is_ok(self):
        report = ps.check_target("linux-arm64", machine="aarch64", system="Linux")
        self.assertTrue(report["ok"])
        self.assertEqual(report["reason"], "host_matches_target")
        self.assertEqual(report["arch"], "arm64")

    def test_cross_arch_is_explicitly_not_verified(self):
        report = ps.check_target("linux-arm64", machine="x86_64", system="Linux")
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "host_arch_mismatch:amd64!=arm64")

    def test_non_linux_and_unknown_arch_are_reported(self):
        self.assertEqual(ps.check_target("linux-amd64", machine="x86_64", system="Windows")["reason"],
                         "host_system_mismatch:windows!=linux")
        self.assertEqual(ps.check_target("linux-amd64", machine="mips", system="Linux")["reason"],
                         "unknown_arch:mips")

    def test_macos_targets_require_darwin_and_matching_arch(self):
        ok = ps.check_target("macos-arm64", machine="arm64", system="Darwin", translated=False)
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["system"], "darwin")
        wrong_system = ps.check_target("macos-arm64", machine="arm64", system="Linux")
        self.assertEqual(wrong_system["reason"], "host_system_mismatch:linux!=darwin")
        wrong_arch = ps.check_target("macos-arm64", machine="x86_64", system="Darwin",
                                     translated=False)
        self.assertEqual(wrong_arch["reason"], "host_arch_mismatch:amd64!=arm64")
        intel = ps.check_target("macos-amd64", machine="x86_64", system="Darwin", translated=False)
        self.assertTrue(intel["ok"])
        self.assertEqual(intel["arch"], "amd64")

    def test_rosetta_is_not_intel_hardware(self):
        report = ps.check_target("macos-amd64", machine="x86_64", system="Darwin", translated=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "rosetta_translation:not_native")
        native = ps.check_target("macos-amd64", machine="x86_64", system="Darwin", translated=False)
        self.assertTrue(native["ok"])

    def test_matrix_marks_only_the_real_host(self):
        matrix = ps.matrix()
        rows = {row["target"]: row for row in matrix["rows"]}
        self.assertEqual(set(rows), {"linux-amd64", "linux-arm64", "macos-arm64", "macos-amd64"})
        verified = [row["target"] for row in matrix["rows"] if row["verified_here"]]
        self.assertLessEqual(len(verified), 1, "同一次运行不可能同时是真机 amd64 和 arm64")
        self.assertEqual(rows["macos-arm64"]["launcher"], "launchd")
        self.assertEqual(rows["macos-amd64"]["system"], "darwin")


class ArchTest(unittest.TestCase):

    def test_machine_names_are_normalized(self):
        self.assertEqual(ps.normalize_arch("x86_64"), "amd64")
        self.assertEqual(ps.normalize_arch("AMD64"), "amd64")
        self.assertEqual(ps.normalize_arch("aarch64"), "arm64")
        self.assertEqual(ps.normalize_arch(" arm64 "), "arm64")

    def test_unknown_machine_is_not_guessed(self):
        self.assertEqual(ps.normalize_arch("riscv64"), "")
        self.assertEqual(ps.normalize_arch(""), "")
        self.assertEqual(ps.normalize_arch(None), "")

    def test_target_lookup_roundtrip(self):
        self.assertEqual(ps.target_for_arch("arm64"), "linux-arm64")
        self.assertEqual(ps.target_for_arch("amd64"), "linux-amd64")
        self.assertEqual(ps.target_for_arch("mips"), "")
        with self.assertRaises(ps.TargetError):
            ps.check_target("linux-s390x")
