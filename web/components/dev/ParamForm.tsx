import styles from "@/components/dev/dev.module.css";
import { type JsonSchema, type ParamField, getPath, paramFields } from "@/lib/devapi";

export type EditValue = string | number | boolean;
// Edited values by dotted path. Only fields that differ from the run's own value are present.
export type Edits = Record<string, EditValue>;

// One stage's parameters, as inputs bounded by the Params schema. Values start as the run's own params;
// an edit that matches the run's value is reported as undefined (no change).
export default function ParamForm({
  keys,
  schema,
  params,
  edits,
  disabled,
  onEdit,
}: {
  keys: string[];
  schema: JsonSchema;
  params: Record<string, unknown>;
  edits: Edits;
  disabled: boolean;
  onEdit: (path: string, value: EditValue | undefined) => void;
}) {
  const fields = keys.flatMap((key) => paramFields(schema, key));
  if (fields.length === 0) return <p className={styles.muted}>No parameters.</p>;
  return (
    <div className={styles.fields}>
      {fields.map((f) => {
        const original = getPath(params, f.path) ?? f.default;
        const value = f.path in edits ? edits[f.path] : original;
        return (
          <Field
            key={f.path}
            field={f}
            value={value}
            disabled={disabled}
            onChange={(next) => onEdit(f.path, next === original ? undefined : next)}
          />
        );
      })}
    </div>
  );
}

function Field({
  field,
  value,
  disabled,
  onChange,
}: {
  field: ParamField;
  value: unknown;
  disabled: boolean;
  onChange: (next: EditValue) => void;
}) {
  const id = `param-${field.path}`;
  const range = field.min !== undefined && field.max !== undefined ? `${field.min} to ${field.max}` : null;
  let input: React.ReactNode;
  if (field.kind === "boolean") {
    input = (
      <input id={id} type="checkbox" checked={Boolean(value)} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
    );
  } else if (field.kind === "enum") {
    input = (
      <select id={id} value={String(value)} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {(field.options ?? []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  } else if (field.kind === "text") {
    input = (
      <input id={id} type="text" value={String(value ?? "")} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
    );
  } else {
    // A value that is not a number (e.g. cleared) is sent as typed, and the API refuses it with 422.
    input = (
      <input
        id={id}
        type="number"
        step={field.kind === "integer" ? 1 : "any"}
        min={field.min}
        max={field.max}
        value={value === undefined ? "" : String(value)}
        disabled={disabled}
        onChange={(e) => {
          const raw = e.target.value;
          const num = raw.trim() === "" ? NaN : Number(raw);
          onChange(Number.isNaN(num) ? raw : num);
        }}
      />
    );
  }
  return (
    <div className={styles.field}>
      <label htmlFor={id}>{field.path}</label>
      {input}
      {range ? <small>{range}</small> : null}
    </div>
  );
}
