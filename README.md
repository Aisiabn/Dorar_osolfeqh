# موسوعة أصول الفقه — أرشفة شخصية

أداة استخراج موسوعة أصول الفقه من [dorar.net/osolfeqh](https://dorar.net/osolfeqh) بصيغة JSON منظمة.

## البنية

```
.
├── scraper.py        # المستخرج الرئيسي
├── exporter.py       # تحويل JSON → Markdown/CSV
├── requirements.txt
└── data/
    ├── raw/          # HTML خام (اختياري)
    └── output/       # ملفات JSON النهائية
```

## التشغيل

```bash
pip install -r requirements.txt
python scraper.py
```

الخيارات:
```bash
python scraper.py --delay 2        # تأخير بين الطلبات (ثانية)
python scraper.py --raw            # حفظ HTML الخام أيضًا
python scraper.py --resume         # استئناف من حيث توقف
```

## الناتج

```json
{
  "id": "bab-1-fasl-2",
  "title": "تعريف أصول الفقه",
  "path": ["الباب الأول", "الفصل الثاني"],
  "content": "...",
  "url": "https://dorar.net/osolfeqh/..."
}
```

## ملاحظات
- الأداة للأرشفة الشخصية فقط
- تحترم `robots.txt` وتضيف تأخيرًا بين الطلبات
- لا ترفع المحتوى المستخرج علنًا
