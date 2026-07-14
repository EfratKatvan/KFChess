from __future__ import annotations

import pathlib

import cv2
import numpy as np


class Img:
    """עטיפה דקה סביב opencv לטעינה/ציור של תמונות - מבוססת על py/img.py
    מ-https://github.com/KamaTechOrg/CTD26 (הנכס הגרפי היחיד המורשה
    לפרויקט הזה). show() כאן לא-חוסם כברירת מחדל (wait_ms=1), בניגוד
    למקור שתמיד חסם עם waitKey(0) - כדי להתאים ללולאת זמן-אמת."""

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
        """הופכת רקע כמעט-אחיד (נדגם מארבע הפינות של התמונה) לשקוף - עבור
        תמונות בלי ערוץ alpha אמיתי (כמו כלי pieces1 ב-CTD26, שיש להן ריבוע
        רקע צבוע-מלא מאחורי הצללית, בניגוד ל-pieces2 שכבר מגיעות עם alpha
        אמיתי). על תמונה שכבר יש לה 4 ערוצים לא עושה כלום - אין צורך."""
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

    def put_text(self, txt, x, y, font_size, color=(255, 255, 255, 255), thickness=1):
        if self.img is None:
            raise ValueError("Image not loaded.")
        cv2.putText(self.img, txt, (x, y),
                    cv2.FONT_HERSHEY_SIMPLEX, font_size,
                    color, thickness, cv2.LINE_AA)

    def show(self, window_name: str = "Image", wait_ms: int = 1) -> int:
        """מציג את התמונה בחלון cv2. wait_ms=1 (ברירת מחדל) לא חוסם - מתאים
        ללולאת רינדור בזמן-אמת. מחזיר את קוד המקש שנלחץ (cv2.waitKey).

        אם יש ל-self.img ערוץ alpha, ממירים ל-BGR לפני ההצגה - הבלנדינג
        (שקיפות הרקע של הכלים) כבר בוצע בעצמנו ב-draw_on לתוך ערוצי ה-BGR,
        אז אין צורך ב-alpha בשלב התצוגה - ול-cv2.imshow יש התנהגות לא
        עקבית בהצגת תמונות עם 4 ערוצים (ההבדל בין imwrite לבין imshow
        בפועל)."""
        if self.img is None:
            raise ValueError("Image not loaded.")
        display_img = cv2.cvtColor(self.img, cv2.COLOR_BGRA2BGR) if self.img.shape[2] == 4 else self.img
        cv2.imshow(window_name, display_img)
        return cv2.waitKey(wait_ms)
