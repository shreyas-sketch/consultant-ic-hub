// The only way rich HTML reaches the screen. Message bodies, AI drafts and page blocks
// can contain text that came from clients or a model, so every render is sanitised:
// no scripts, no event handlers, no javascript: links, no embedded frames or forms.
import DOMPurify from "dompurify";

const CONFIG = {
  USE_PROFILES: { html: true },
  FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "iframe", "object", "embed"],
  FORBID_ATTR: ["style"],
};

// Links open in a new tab and can't reach back into the app.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.getAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

export const sanitize = (html) => DOMPurify.sanitize(String(html ?? ""), CONFIG);

export function SafeHtml({ html, as: Tag = "div", ...rest }) {
  return <Tag {...rest} dangerouslySetInnerHTML={{ __html: sanitize(html) }} />;
}
