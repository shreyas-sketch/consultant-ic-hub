// The one import for talking to the backend: `import { act, useAct, useDo } from "@/shared/api"`.
export { ApiError, act, get, post, req } from "./client";
export { useAct, useDo, useRefresh } from "./hooks";
// Kept here so existing imports keep working; new code imports from "@/shared/lib/files".
export { download, fileToDataUrl, parseCsv } from "@/shared/lib/files";
