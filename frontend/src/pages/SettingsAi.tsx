import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, CheckCircle2, ShieldCheck, Sparkles } from "lucide-react";
import { useGroupCtx } from "../components/layout/Shell";
import { useAiSettings, useSaveAiSettings, useTestAiSettings } from "../hooks/useAiSettings";
import { useToast } from "../components/ui/Toast";
import { ErrorState } from "../components/ui/EmptyState";
import { PageSpinner } from "../components/ui/Spinner";
import { AI_PRESETS, AI_PROVIDER_OPTIONS } from "../config/aiProviders";
import { ApiError } from "../lib/api";
import type { AiProvider, AiSettingsPut } from "../types/api";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export default function SettingsAi() {
  const { gid } = useGroupCtx();
  const settings = useAiSettings();
  const save = useSaveAiSettings();
  const test = useTestAiSettings();
  const { toast } = useToast();

  const [provider, setProvider] = useState<AiProvider>("gemini");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [key, setKey] = useState("");
  const [keySaved, setKeySaved] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  // Hydrate from the server whenever the saved settings change. The key is
  // never returned, so the field stays blank and keySaved drives the hint.
  useEffect(() => {
    const d = settings.data;
    if (!d) return;
    // A fresh account returns provider/base_url/model null. Land on the
    // recommended default and prefill its preset so the first Save works
    // without the user re-picking the provider from the dropdown.
    const nextProvider: AiProvider = d.provider ?? "gemini";
    setProvider(nextProvider);
    const preset = nextProvider !== "custom" ? AI_PRESETS[nextProvider] : null;
    setModel(d.model || preset?.model || "");
    setBaseUrl(d.base_url || preset?.base_url || "");
    setKeySaved(d.key_set);
    setKey("");
    setFormError(null);
    setTestResult(null);
  }, [settings.data]);

  const changeProvider = (next: AiProvider) => {
    setProvider(next);
    setFormError(null);
    setTestResult(null);
    if (next !== "custom") {
      // Prefill the preset; the model stays editable afterwards.
      setModel(AI_PRESETS[next].model);
      setBaseUrl(AI_PRESETS[next].base_url);
    }
  };

  const saved = settings.data;
  const dirty =
    saved != null &&
    (provider !== saved.provider ||
      model.trim() !== saved.model ||
      (provider === "custom" && baseUrl.trim() !== saved.base_url) ||
      key.trim().length > 0);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (model.trim().length === 0) {
      setFormError("Model is required.");
      return;
    }
    if (provider === "custom" && baseUrl.trim().length === 0) {
      setFormError("Base URL is required for a custom provider.");
      return;
    }
    setFormError(null);
    setTestResult(null);
    const payload: AiSettingsPut = { provider, model: model.trim() };
    if (provider === "custom") payload.base_url = baseUrl.trim();
    // A blank key keeps the stored one; only send a value the user typed.
    if (key.trim().length > 0) payload.key = key.trim();
    save.mutate(payload, {
      onSuccess: () => toast("AI settings saved"),
      onError: (err) => setFormError(errMsg(err, "Couldn't save AI settings. Retry.")),
    });
  };

  const runTest = async () => {
    if (dirty) {
      setTestResult({ ok: false, text: "Save your changes first, then send a test." });
      return;
    }
    if (!keySaved) {
      setTestResult({ ok: false, text: "Add and save an API key first." });
      return;
    }
    setTestResult(null);
    try {
      const res = await test.mutateAsync();
      setTestResult(
        res.ok
          ? { ok: true, text: "The provider replied. Your key works." }
          : { ok: false, text: res.error ?? "The provider rejected the request." },
      );
    } catch (err) {
      setTestResult({ ok: false, text: errMsg(err, "Couldn't reach the provider. Retry.") });
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <Link
        to={`/g/${gid}`}
        className="inline-flex items-center gap-1.5 text-sm text-muted transition-colors duration-150 ease-out hover:text-ink"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        Back to dashboard
      </Link>

      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-ink">
          <Sparkles className="h-5 w-5 text-muted" aria-hidden />
          AI settings
        </h1>
        <p className="mt-1 text-sm text-muted">
          Bring your own key to tailor resumes. Your key is stored encrypted and used only for your
          own requests.
        </p>
      </div>

      {settings.isPending ? (
        <PageSpinner label="Loading AI settings" />
      ) : settings.isError ? (
        <ErrorState
          message="Couldn't load your AI settings. Retry."
          onRetry={() => settings.refetch()}
        />
      ) : (
        <section className="card p-5">
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label htmlFor="ai-provider" className="label">
                Provider
              </label>
              <select
                id="ai-provider"
                className="input"
                value={provider}
                onChange={(e) => changeProvider(e.target.value as AiProvider)}
              >
                {AI_PROVIDER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="ai-key" className="label">
                API key
              </label>
              <input
                id="ai-key"
                type="password"
                className="input font-mono"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="Paste your key - it is stored encrypted"
                autoComplete="off"
                spellCheck={false}
              />
              {keySaved && (
                <p className="mt-1 flex items-center gap-1.5 text-[11px] text-muted">
                  <ShieldCheck className="h-3 w-3 text-status-offer-text" aria-hidden />
                  A key is saved. Leave this blank to keep it.
                </p>
              )}
            </div>

            <div>
              <label htmlFor="ai-model" className="label">
                Model
              </label>
              <input
                id="ai-model"
                className="input font-mono"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="e.g. gemini-2.0-flash"
                spellCheck={false}
              />
            </div>

            <div>
              <label htmlFor="ai-base-url" className="label">
                Base URL
              </label>
              <input
                id="ai-base-url"
                className="input font-mono"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://your-provider/v1"
                readOnly={provider !== "custom"}
                aria-readonly={provider !== "custom"}
                spellCheck={false}
              />
              <p className="mt-1 text-[11px] text-muted">
                {provider === "custom"
                  ? "Any OpenAI-compatible endpoint works."
                  : "Set automatically for this provider."}
              </p>
            </div>

            <p className="rounded-md border border-line bg-canvas p-3 text-xs leading-relaxed text-muted">
              Your resume and this job description are sent to the AI provider you configure. Free
              tiers may use data for training.
            </p>
            <p className="text-[11px] text-muted">
              Get a free key at aistudio.google.com (Gemini) or console.groq.com (Groq).
            </p>

            {formError && (
              <p role="alert" className="text-sm text-danger">
                {formError}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <button type="submit" className="btn-primary" disabled={save.isPending}>
                {save.isPending ? "Saving..." : "Save"}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={runTest}
                disabled={test.isPending}
              >
                {test.isPending ? "Testing..." : "Send test message"}
              </button>
            </div>

            {testResult && (
              <div
                role="status"
                className={
                  testResult.ok
                    ? "flex items-start gap-2 rounded-md border border-line bg-canvas p-3 text-sm text-ink"
                    : "flex items-start gap-2 rounded-md border border-line bg-canvas p-3 text-sm"
                }
              >
                {testResult.ok ? (
                  <CheckCircle2
                    className="mt-0.5 h-4 w-4 shrink-0 text-status-offer-text"
                    aria-hidden
                  />
                ) : null}
                <span className={testResult.ok ? "text-ink" : "text-danger"}>
                  {testResult.text}
                </span>
              </div>
            )}
          </form>
        </section>
      )}
    </div>
  );
}
