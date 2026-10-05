import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import AssistantMarkdown from "../components/assistant-markdown";

function render(content: string) {
  return renderToStaticMarkup(React.createElement(AssistantMarkdown, { content }));
}

for (const content of [
  "[Модель](https://ladzavod.ru/catalog/r700)",
  "https://ladzavod.ru/catalog/r700",
  "[Относительная ссылка](/catalog/r700)",
]) {
  test(`assistant link opens outside chat: ${content}`, () => {
    const html = render(content);
    assert.match(html, /<a /);
    assert.match(html, /target="_blank"/);
    assert.match(html, /rel="noopener noreferrer"/);
  });
}

test("unsafe Markdown URLs remain sanitized", () => {
  assert.doesNotMatch(render("[unsafe](javascript:alert%281%29)"), /href="javascript:/);
});
