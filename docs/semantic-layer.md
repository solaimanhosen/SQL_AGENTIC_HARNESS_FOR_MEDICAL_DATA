# The semantic layer

The agent does not guess what a question means. Terms such as "diabetic patient" or "ER
visit" are defined once, in files the whole team can read and review, and every answer says
which definition it used. This document explains what is in those files and how to add to
them.

Two files hold the content, both under `Backend/sql_agent/semantic/`:

| File | Holds |
|---|---|
| `schema_catalog.yaml` | What each table means, what each column holds, how tables join, and which values a column can take. |
| `definitions.yaml` | The shared definitions: code sets, filters, expressions and grade tables. |

Run the checker after any change. It compares the catalog against the live database and
runs every definition against the data:

```bash
cd Backend
.venv/bin/python -m sql_agent.check_semantics
.venv/bin/python -m sql_agent.check_semantics --show-prompt   # see what the agent will read
```

## Why definitions are written down

In this data, asking for patients whose condition mentions "diabet" returns 37 people.
Only 8 of them have diabetes. The rest have prediabetes, which is a different clinical
state with a different code. A definition that lives in one file, is reviewed once and is
checked against the data prevents that error from reappearing in every new question.

## Adding a definition

Add an entry under `definitions:` in `definitions.yaml`. A minimal one looks like this:

```yaml
  asthma:
    label: Patient with asthma
    kind: cohort
    status: assumed
    summary: Patients with an asthma diagnosis.
    applies_to: conditions
    sql: SELECT DISTINCT patient FROM conditions WHERE code IN (195967001)
    codes:
      195967001: Asthma
    checks:
      - description: Patients with asthma
        sql: SELECT COUNT(*) FROM ({sql})
        equals: 12
```

The fields:

- **kind** is one of four shapes. `cohort` returns patient identifiers. `filter` is a WHERE
  predicate for one table. `expression` computes a value, such as age. `grade_table` bands a
  value into named groups, such as age bands or A1c thresholds.
- **status** is `assumed` until Telligen confirms it, then `confirmed`. The agent tells
  users when an answer rests on an assumed definition, so this field is not decoration.
- **sql** is the fragment the agent uses. Write it for the `kind` you chose.
- **codes** and **excludes** document each code in plain language. Excluding a code is a
  decision, so record why, as the diabetes definition does for prediabetes.
- **notes** carry warnings an analyst would otherwise learn the hard way.
- **checks** are required. Each runs its SQL and compares the single value it returns
  against `equals`, `min` or `max`.

Two placeholders are substituted before a query runs. `{as_of}` becomes the as-of date, and
`{sql}` inside a check becomes that definition's own SQL, so a code list is written once.

### Choosing the expectation

Use `equals` when the number is a fact worth protecting, such as the size of a cohort. A
reload that changes it should fail loudly. Use `min` when you only care that the definition
matches something, for example when the exact count is incidental.

## Adding or changing a table description

Add an entry under `tables:` in `schema_catalog.yaml` with a grain, a description and the
columns worth documenting. Not every column needs an entry, but each one you name must
exist. The test suite fails if the catalog names a table or column the database does not
have, if a documented list of allowed values disagrees with the data, or if a blocked
identity column is documented.

Say how a column joins inside its description, for example "Joins to patients.id". The
agent reads these descriptions as its map of the database.

## The as-of date

Relative windows such as "the last 12 months" count back from the latest date in the data,
which is 2026-08-16, rather than from today. The reasoning is in
[0002-as-of-date.md](decisions/0002-as-of-date.md). Change it with `SQL_AGENT_AS_OF_DATE`,
which accepts `latest`, `today` or a fixed date.

## Review with Telligen

Every definition currently carries `status: assumed`. Two need a decision before they can
be confirmed:

- Whether urgent care counts as an emergency visit. Today it does not.
- What a hospital visit means. Today it counts emergency and inpatient encounters, and
  excludes outpatient and ambulatory care that also happens at hospitals.

Two more are worth raising, because the data disagrees with itself. Only 2 patients ever
record a hemoglobin A1c in the diabetes range while 8 carry a diabetes diagnosis, and 36
patients have a diabetes self management care plan. A cohort built from lab results, from
diagnoses or from care plans gives three different answers to the same question.
