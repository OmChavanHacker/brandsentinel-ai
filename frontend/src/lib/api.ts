export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

function responseDetail(payload: unknown): string | undefined {
  if (typeof payload === "string" && payload.trim()) return payload;
  if (!payload || typeof payload !== "object") return undefined;

  const data = payload as { detail?: unknown; message?: unknown };
  const detail = data.detail ?? data.message;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== "object") return String(item);
        const validationError = item as { loc?: unknown[]; msg?: unknown };
        const location = Array.isArray(validationError.loc)
          ? `${validationError.loc.join(".")}: `
          : "";
        return `${location}${String(validationError.msg ?? JSON.stringify(item))}`;
      })
      .join("; ");
  }
  if (detail !== undefined) return JSON.stringify(detail);
  return undefined;
}

export async function apiFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(input, init);
  } catch (error: unknown) {
    const cause =
      error instanceof Error && !(error instanceof TypeError)
        ? ` (${error.message})`
        : "";
    throw new Error(
      `Cannot reach the BrandSentinel API at ${API_BASE_URL}. Check that the backend is running and that its CORS settings allow this frontend.${cause}`,
    );
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      detail = responseDetail(await response.clone().json());
    } catch {
      try {
        detail = responseDetail(await response.clone().text());
      } catch {
        detail = undefined;
      }
    }

    const status = `${response.status} ${response.statusText}`.trim();
    throw new Error(
      `API request failed (${status})${detail ? `: ${detail}` : "."}`,
    );
  }

  return response;
}
