from __future__ import annotations

import pathlib

import cv2
import numpy as np


class Img:
    """A thin wrapper around opencv for loading/drawing images - based
    on py/img.py from https://github.com/KamaTechOrg/CTD26 (the only
    graphics asset authorized for this project). show() here is
    non-blocking by default (wait_ms=1), unlike the original which
    always blocked with waitKey(0) - to fit a real-time render loop."""

    def __init__(self):
        self.img = None

    def read(self, path: str | pathlib.Path,
             size: tuple[int, int] | None = None,
             keep_aspect: bool = False,
             interpolation: int = cv2.INTER_AREA) -> "Img":
        path = str(path)
        self.img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if self.img is None:
            raise FileNotFoundError(f"Cannot load image: {path}")

        if size is not None:
            self.resize(size, keep_aspect=keep_aspect, interpolation=interpolation)

        return self

    def resize(self, size: tuple[int, int], keep_aspect: bool = False,
               interpolation: int = cv2.INTER_AREA) -> "Img":
        if self.img is None:
            raise ValueError("Image not loaded.")

        target_w, target_h = size
        h, w = self.img.shape[:2]

        if keep_aspect:
            scale = min(target_w / w, target_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
        else:
            new_w, new_h = target_w, target_h

        self.img = cv2.resize(self.img, (new_w, new_h), interpolation=interpolation)
        return self

    def draw_on(self, other_img: "Img", x: int, y: int) -> None:
        if self.img is None or other_img.img is None:
            raise ValueError("Both images must be loaded before drawing.")

        if self.img.shape[2] != other_img.img.shape[2]:
            if self.img.shape[2] == 3 and other_img.img.shape[2] == 4:
                self.img = cv2.cvtColor(self.img, cv2.COLOR_BGR2BGRA)
            elif self.img.shape[2] == 4 and other_img.img.shape[2] == 3:
                self.img = cv2.cvtColor(self.img, cv2.COLOR_BGRA2BGR)

        h, w = self.img.shape[:2]
        H, W = other_img.img.shape[:2]

        if y + h > H or x + w > W:
            raise ValueError("Logo does not fit at the specified position.")

        roi = other_img.img[y:y + h, x:x + w]

        if self.img.shape[2] == 4:
            b, g, r, a = cv2.split(self.img)
            mask = a / 255.0
            for c in range(3):
                roi[..., c] = (1 - mask) * roi[..., c] + mask * self.img[..., c]
        else:
            other_img.img[y:y + h, x:x + w] = self.img

    def strip_background(self, tolerance: int = 30) -> "Img":
        """Turns a near-uniform background (sampled from the image's four
        corners) transparent - for images without a real alpha channel
        (like CTD26's pieces1, which have a solid-colored square behind
        the silhouette, unlike pieces2 which already come with real
        alpha). A no-op on an image that already has 4 channels."""
        if self.img is None:
            raise ValueError("Image not loaded.")
        if self.img.shape[2] == 4:
            return self

        corners = np.array(
            [self.img[0, 0], self.img[0, -1], self.img[-1, 0], self.img[-1, -1]],
            dtype=np.int16,
        )
        background_color = np.median(corners, axis=0)

        diff = np.abs(self.img.astype(np.int16) - background_color)
        is_background = np.all(diff <= tolerance, axis=-1)

        b, g, r = cv2.split(self.img)
        alpha = np.where(is_background, 0, 255).astype(np.uint8)
        self.img = cv2.merge([b, g, r, alpha])
        return self

    def draw_rect(self, x: int, y: int, width: int, height: int, color, thickness: int = 3) -> None:
        if self.img is None:
            raise ValueError("Image not loaded.")
        cv2.rectangle(self.img, (x, y), (x + width - 1, y + height - 1), color, thickness)

    def put_text(self, txt, x, y, font_size, color=(255, 255, 255, 255), thickness=1):
        if self.img is None:
            raise ValueError("Image not loaded.")
        cv2.putText(self.img, txt, (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, font_size,
                    color, thickness, cv2.LINE_AA)

    def text_size(self, txt, font_size, thickness=1) -> tuple[int, int]:
        """So text can be centered before it's actually drawn with put_text."""
        (width, height), _baseline = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, font_size, thickness)
        return width, height

    def show(self, window_name: str = "Image", wait_ms: int = 1) -> int:
        """Shows the image in a cv2 window. wait_ms=1 (default) is
        non-blocking - fits a real-time render loop. Returns the key
        code that was pressed (cv2.waitKey).

        If self.img has an alpha channel, it's converted to BGR before
        display - the blending (piece background transparency) was
        already done ourselves in draw_on into the BGR channels, so no
        alpha is needed at display time - and cv2.imshow behaves
        inconsistently with 4-channel images (the gap between imwrite
        and imshow in practice)."""
        if self.img is None:
            raise ValueError("Image not loaded.")
        display_img = cv2.cvtColor(self.img, cv2.COLOR_BGRA2BGR) if self.img.shape[2] == 4 else self.img
        cv2.imshow(window_name, display_img)
        return cv2.waitKey(wait_ms)
