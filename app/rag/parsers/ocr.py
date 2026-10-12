import hashlib
import json
from functools import lru_cache
from pathlib import Path
from threading import RLock

from app.core.errors import AppError

# PDFium calls, including opening/closing handles, cannot overlap between threads.
pdfium_lock = RLock()
inference_lock = RLock()


@lru_cache(maxsize=1)
def get_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR(intra_op_num_threads=4, inter_op_num_threads=1)
    except Exception as exc:
        raise AppError(
            "ocr_unavailable", "本地 OCR 无法启动，请安装项目依赖后重启服务", 503
        ) from exc


class PageOCR:
    def __init__(
        self, path: Path, dpi: int, cache_dir: Path | None = None, digest: str | None = None
    ):
        self.dpi, self.cache_dir = dpi, cache_dir
        if cache_dir is not None:
            if digest is None:
                with path.open("rb") as file:
                    digest = hashlib.file_digest(file, "sha256").hexdigest()
            self.fingerprint = f"{digest}:rapidocr-1.4-v1:{dpi}"
            cache_dir.mkdir(parents=True, exist_ok=True)

    def read(self, page, number: int) -> str:
        target = self.cache_dir / f"page-{number}.json" if self.cache_dir else None
        if target and target.exists():
            try:
                cached = json.loads(target.read_text("utf-8"))
                if cached["fingerprint"] == self.fingerprint and isinstance(cached["text"], str):
                    return cached["text"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        try:
            with pdfium_lock:
                width, height = page.get_size()
                scale = min(self.dpi / 72, 2400 / max(width, height))
                bitmap = page.render(scale=scale)
                try:
                    pixels = bitmap.to_numpy().copy()
                finally:
                    bitmap.close()
            if int(pixels.max()) - int(pixels.min()) < 5:
                text = ""
            else:
                with inference_lock:
                    result, _ = get_engine()(pixels)
                text = "\n".join(row[1].strip() for row in (result or []) if row[1].strip())
            if target:
                temporary = target.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps({"fingerprint": self.fingerprint, "text": text}, ensure_ascii=False),
                    encoding="utf-8",
                )
                temporary.replace(target)
            return text
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                "ocr_failed", f"第 {number} 页 OCR 识别失败，请重试；已识别页面会复用", 500
            ) from exc


def delete_ocr_cache(data_dir: Path, document_id: str):
    root = (data_dir / "ocr").resolve()
    cache = (root / document_id).resolve()
    if cache.parent != root or cache.name != document_id:
        raise AppError("invalid_ocr_path", "OCR 缓存路径异常，未执行删除", 500)
    if not cache.exists():
        return
    for file in cache.iterdir():
        if (
            file.resolve().parent != cache
            or not file.is_file()
            or file.suffix not in {".json", ".tmp"}
        ):
            raise AppError("invalid_ocr_path", "OCR 缓存文件异常，请检查后重试删除", 500)
    for file in cache.iterdir():
        file.unlink()
    cache.rmdir()
