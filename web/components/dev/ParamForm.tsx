import styles from "@/components/dev/dev.module.css";
import { type JsonSchema, type ParamField, getPath, paramFields, STAGE_PARAM_KEYS } from "@/lib/devapi";

// One stage's parameters, as inputs bounded by the Params schema. Every control is disabled:
// the panel is read-only until sign-in (ticket 13b). Values are the run's own params.
export default function ParamForm({
  stage,
  schema,
  params,
}: {
  stage: string;
  schema: JsonSchema;
  params: Record<string, unknown>;
}) {
  const fields = (STAGE_PARAM_KEYS[stage] ?? []).flatMap((key) => paramFields(schema, key));
  if (fields.length === 0) return <p className={styles.muted}>No parameters.</p>;
  return (
    <div className={styles.fields}>
      {fields.map((f) => (
        <Field key={f.path} field={f} value={getPath(params, f.path) ?? f.default} />
      ))}
    </div>
  );
}

function Field({ field, value }: { field: ParamField; value: unknown }) {
  const id = `param-${field.path}`;
  const range =
    field.min !== undefined && field.max !== undefined ? `${field.min} to ${field.max}` : null;
  let input: React.ReactNode;
  if (field.kind === "boolean") {
    input = <input id={id} type="checkbox" defaultChecked={Boolean(value)} disabled />;
  } else if (field.kind === "enum") {
    input = (
      <select id={id} defaultValue={String(value)} disabled>
        {(field.options ?? []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  } else if (field.kind === "text") {
    input = <input id={id} type="text" defaultValue={String(value ?? "")} disabled />;
  } else {
    input = (
      <input
        id={id}
        type="number"
        step={field.kind === "integer" ? 1 : "any"}
        min={field.min}
        max={field.max}
        defaultValue={value === undefined ? "" : String(value)}
        disabled
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
