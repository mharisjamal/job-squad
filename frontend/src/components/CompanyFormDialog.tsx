import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Dialog } from "./ui/Dialog";
import { normalizeUrl } from "../lib/format";
import type { Company, CompanyDetail, CompanyPayload } from "../types/api";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  initial?: Company | CompanyDetail | null;
  busy: boolean;
  error: string | null;
  onSubmit: (payload: CompanyPayload) => void;
}

export function CompanyFormDialog({ open, onClose, title, initial, busy, error, onSubmit }: Props) {
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [careersUrl, setCareersUrl] = useState("");
  const [location, setLocation] = useState("");
  const [tags, setTags] = useState("");
  const [notes, setNotes] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(initial?.name ?? "");
    setWebsite(initial?.website ?? "");
    setCareersUrl(initial?.careers_url ?? "");
    setLocation(initial?.location ?? "");
    setTags(initial?.tags.join(", ") ?? "");
    setNotes(initial?.notes ?? "");
    setLocalError(null);
  }, [open, initial]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim().length === 0) {
      setLocalError("Company name is required.");
      return;
    }
    setLocalError(null);
    onSubmit({
      name: name.trim(),
      website: normalizeUrl(website) || null,
      careers_url: normalizeUrl(careersUrl) || null,
      location: location.trim() || null,
      tags: tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      notes: notes.trim() || null,
    });
  };

  const shownError = localError ?? error;

  return (
    <Dialog open={open} onClose={onClose} title={title} wide>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label htmlFor="company-name" className="label">
              Name
            </label>
            <input
              id="company-name"
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. TechCorp"
            />
          </div>
          <div>
            <label htmlFor="company-website" className="label">
              Website
            </label>
            <input
              id="company-website"
              className="input"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
              placeholder="https://techcorp.com"
              inputMode="url"
            />
          </div>
          <div>
            <label htmlFor="company-careers" className="label">
              Careers URL
            </label>
            <input
              id="company-careers"
              className="input"
              value={careersUrl}
              onChange={(e) => setCareersUrl(e.target.value)}
              placeholder="https://techcorp.com/careers"
              inputMode="url"
            />
          </div>
          <div>
            <label htmlFor="company-location" className="label">
              Location
            </label>
            <input
              id="company-location"
              className="input"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="e.g. Remote, Karachi, Berlin"
            />
          </div>
          <div>
            <label htmlFor="company-tags" className="label">
              Tags
            </label>
            <input
              id="company-tags"
              className="input"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="fintech, remote, dream (comma-separated)"
            />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="company-notes" className="label">
              Shared notes
            </label>
            <textarea
              id="company-notes"
              className="input min-h-20 resize-y"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Facts the whole squad should know (stack, referrals, salary intel...)"
              rows={3}
            />
          </div>
        </div>
        {shownError && (
          <p role="alert" className="text-sm text-danger">
            {shownError}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? "Saving..." : "Save company"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
