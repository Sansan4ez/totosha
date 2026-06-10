import unittest

from core.web_artifacts import extract_ui_artifact


class WebArtifactsTests(unittest.TestCase):
    def test_extracts_bar_chart_from_numeric_markdown_table(self):
        text = """# Price comparison

| Model | Score |
| --- | ---: |
| A | 12 |
| B | 18 |
"""

        cleaned, artifact = extract_ui_artifact(text, "web")

        self.assertEqual(cleaned, text)
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact["type"], "component_tree")
        children = artifact["payload"]["root"]["children"]
        self.assertEqual(children[0]["name"], "header")
        self.assertEqual(children[1]["name"], "bar_chart")

    def test_extracts_item_card_from_field_list(self):
        text = """Title: Widget Pro
Description: Compact embedded chat shell.
Price: 14900 RUB
CTA: Learn more
"""

        _, artifact = extract_ui_artifact(text, "web")

        self.assertIsNotNone(artifact)
        root = artifact["payload"]["root"]
        self.assertEqual(root["name"], "item_card")
        self.assertEqual(root["title"], "Widget Pro")
        self.assertEqual(root["cta_label"], "Learn more")

    def test_extracts_explicit_fenced_json_artifact(self):
        text = """Summary

```ui_artifact
{"type":"component_tree","version":"v1","payload":{"root":{"name":"header","content":"Hi"}}}
```
"""

        cleaned, artifact = extract_ui_artifact(text, "web")

        self.assertEqual(cleaned, "Summary")
        self.assertEqual(artifact["payload"]["root"]["name"], "header")

    def test_plain_json_block_remains_plain_text(self):
        text = """Example:

```json
{"ok": true}
```
"""

        cleaned, artifact = extract_ui_artifact(text, "web")

        self.assertEqual(cleaned, text)
        self.assertIsNone(artifact)

    def test_non_web_source_never_extracts_artifact(self):
        text = "Title: Widget Pro"
        cleaned, artifact = extract_ui_artifact(text, "bot")
        self.assertEqual(cleaned, text)
        self.assertIsNone(artifact)


if __name__ == "__main__":
    unittest.main()
