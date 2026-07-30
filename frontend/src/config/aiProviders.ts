import type { AiProvider } from "../types/api";

export interface AiPreset {
  value: AiProvider;
  label: string;
  base_url: string;
  model: string;
}

/**
 * Provider presets mirror IMPLEMENTATION_PLAN.md section 9b (Phase R3). The base
 * URL is server-fixed for the two hosted providers; the model stays editable.
 */
export const AI_PRESETS: Record<Exclude<AiProvider, "custom">, AiPreset> = {
  gemini: {
    value: "gemini",
    label: "Gemini (recommended)",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai/",
    model: "gemini-2.0-flash",
  },
  groq: {
    value: "groq",
    label: "Groq",
    base_url: "https://api.groq.com/openai/v1",
    model: "llama-3.3-70b-versatile",
  },
};

export const AI_PROVIDER_OPTIONS: { value: AiProvider; label: string }[] = [
  { value: "gemini", label: "Gemini (recommended)" },
  { value: "groq", label: "Groq" },
  { value: "custom", label: "Custom" },
];
