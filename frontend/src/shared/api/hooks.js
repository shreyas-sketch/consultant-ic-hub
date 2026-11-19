// React Query bindings for actions. Query keys are [actionName, body], so
// invalidating by prefix ("projects") refreshes every projects.* read.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { act } from "./client";

const startsWithAny = (q, prefixes) => prefixes.some((p) => String(q.queryKey[0]).startsWith(p));

/** Read an action as a query: useAct("projects.search", {q}) */
export function useAct(name, body = {}, opts = {}) {
  return useQuery({ queryKey: [name, body], queryFn: () => act(name, body), ...opts });
}

/** Run an action and refresh what it touches (defaults to the action's own domain). */
export function useDo(name, { invalidate = [], onSuccess, onError } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => act(name, body),
    onSuccess: (data, vars) => {
      const prefixes = invalidate.length ? invalidate : [name.split(".")[0]];
      qc.invalidateQueries({ predicate: (q) => startsWithAny(q, prefixes) });
      onSuccess && onSuccess(data, vars);
    },
    onError,
  });
}

export function useRefresh() {
  const qc = useQueryClient();
  return (...prefixes) => qc.invalidateQueries({ predicate: (q) => !prefixes.length || startsWithAny(q, prefixes) });
}
