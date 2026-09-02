/**
 * Technology names a topic's requirement rows **literally contain**.
 *
 * The compact card wants to be specific — "Cloud Platforms · AWS · GCP" reads
 * as advice where "Cloud Platforms" alone reads as a category. The danger is
 * inventing that specificity: a topic called "Cloud Platforms" must never
 * produce "Azure" because Azure is a cloud, only because a requirement the
 * employer wrote said Azure.
 *
 * So this is a **grounding gate, not an inference**. A term is displayed only
 * when it appears verbatim in one of the topic's own requirement rows, matched
 * on word boundaries. The lexicon cannot add meaning — it can only recognise a
 * string that is already there. A technology missing from the lexicon simply
 * goes unshown (the expanded "What the roles ask" still carries the full text);
 * a technology absent from the evidence can never be shown at all.
 *
 * Ranking is by how many of the topic's rows mention the term, then by lexicon
 * order — deterministic, and it naturally demotes an incidental mention (one
 * cloud posting that happens to name Docker) below the terms the topic is
 * actually about.
 *
 * **Deliberately excluded**: single- and double-character names — Go, R, C —
 * whose word-boundary matches in prose are noise ("go", "R&D", a bare "C").
 * Missing a language is a smaller harm than a card full of false tags.
 */

import type { SpecificRequirement } from "@/lib/api";

type TechTerm = {
  /** What the chip displays. */
  display: string;
  /** Spellings that count as this term, matched verbatim. */
  patterns: string[];
  /**
   * Require the lexicon's own capitalisation.
   *
   * Set for every name that is also an ordinary English word. Matched
   * case-insensitively, "work at a swift pace" showed `Swift`, "taking the helm
   * of a squad" showed `Helm`, and "bring a spark of creativity" showed `Spark`
   * — technologies the employer never named, which is exactly what this module
   * says it can never do. A posting naming the product capitalises it; prose
   * does not.
   *
   * Residual, and accepted rather than hidden: a sentence *beginning* with the
   * word ("React to incidents within 15 minutes") is capitalised and still
   * matches. Narrowing that further would need sentence segmentation, which is
   * inference — the thing this module refuses.
   */
  caseSensitive?: boolean;
};

/** Order is the tie-break, so it is stable and reviewed rather than incidental. */
const LEXICON: TechTerm[] = [
  // Cloud and infrastructure
  { display: "AWS", patterns: ["AWS", "Amazon Web Services"] },
  { display: "GCP", patterns: ["GCP", "Google Cloud"] },
  { display: "Azure", patterns: ["Azure"] },
  { display: "Kubernetes", patterns: ["Kubernetes", "K8s"] },
  { display: "Docker", patterns: ["Docker"] },
  { display: "Terraform", patterns: ["Terraform"] },
  { display: "Helm", patterns: ["Helm"], caseSensitive: true },
  { display: "Serverless", patterns: ["Serverless"] },
  // **Not a bare "Lambda".** "familiar with lambda expressions" is a sentence
  // about closures, and it displayed `Serverless` — a technology the row never
  // named, under a word it did not even match. The unambiguous phrase only.
  { display: "AWS Lambda", patterns: ["AWS Lambda"] },
  // Data
  { display: "PostgreSQL", patterns: ["PostgreSQL", "Postgres"] },
  { display: "MySQL", patterns: ["MySQL"] },
  { display: "MongoDB", patterns: ["MongoDB"] },
  { display: "Redis", patterns: ["Redis"] },
  { display: "SQLAlchemy", patterns: ["SQLAlchemy"] },
  { display: "Elasticsearch", patterns: ["Elasticsearch"] },
  { display: "Kafka", patterns: ["Kafka"] },
  { display: "BigQuery", patterns: ["BigQuery"] },
  { display: "Snowflake", patterns: ["Snowflake"], caseSensitive: true },
  { display: "Airflow", patterns: ["Airflow"], caseSensitive: true },
  { display: "Spark", patterns: ["Spark"], caseSensitive: true },
  { display: "SQL", patterns: ["SQL"] },
  { display: "NoSQL", patterns: ["NoSQL"] },
  // Languages and frameworks
  { display: "Python", patterns: ["Python"] },
  { display: "TypeScript", patterns: ["TypeScript"] },
  { display: "JavaScript", patterns: ["JavaScript"] },
  { display: "Java", patterns: ["Java"] },
  { display: "Node.js", patterns: ["Node.js", "NodeJS"] },
  { display: "React", patterns: ["React"], caseSensitive: true },
  { display: "Django", patterns: ["Django"] },
  { display: "FastAPI", patterns: ["FastAPI"] },
  { display: "Flask", patterns: ["Flask"], caseSensitive: true },
  // **No bare "Spring".** Capitalisation cannot separate the framework from the
  // season: "Spring 2026 internship cohort" is capitalised and is not Java. Only
  // the spellings that can mean nothing else, on the same reasoning as RAG below.
  {
    display: "Spring",
    patterns: ["Spring Boot", "Spring Framework", "Spring MVC"],
    caseSensitive: true,
  },
  { display: ".NET", patterns: [".NET"] },
  { display: "C#", patterns: ["C#"] },
  { display: "C++", patterns: ["C++"] },
  { display: "Ruby", patterns: ["Ruby"], caseSensitive: true },
  { display: "Rust", patterns: ["Rust"], caseSensitive: true },
  { display: "Kotlin", patterns: ["Kotlin"] },
  { display: "Swift", patterns: ["Swift"], caseSensitive: true },
  { display: "PHP", patterns: ["PHP"] },
  { display: "Scala", patterns: ["Scala"] },
  { display: "GraphQL", patterns: ["GraphQL"] },
  { display: "gRPC", patterns: ["gRPC"] },
  // AI
  { display: "LLMs", patterns: ["LLMs", "LLM"] },
  // **The bare acronym is gone.** "RAG status reporting" is standard delivery
  // jargon (red/amber/green) and is capitalised in both meanings, so no case
  // rule separates them. Matching the phrase costs a posting that only ever
  // writes "RAG" — the smaller harm, by this module's own stated preference.
  {
    display: "RAG",
    patterns: ["retrieval-augmented generation", "retrieval augmented generation"],
  },
  { display: "LangChain", patterns: ["LangChain"] },
  { display: "PyTorch", patterns: ["PyTorch"] },
  { display: "TensorFlow", patterns: ["TensorFlow"] },
  // Delivery
  { display: "GitHub Actions", patterns: ["GitHub Actions"] },
  { display: "Jenkins", patterns: ["Jenkins"] },
];

function escape(pattern: string): string {
  return pattern.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Word-boundary match that also refuses a hit inside a longer token, so
 *  "SQL" does not match within "PostgreSQL" or "NoSQL".
 *
 *  The boundary class excludes `.` deliberately: a sentence-final "Docker."
 *  must still match, and terms that genuinely contain a dot (".NET",
 *  "Node.js") are matched literally by their own pattern. */
function mentions(text: string, pattern: string, caseSensitive = false): boolean {
  const boundary = "[A-Za-z0-9+#]";
  return new RegExp(
    `(?<!${boundary})${escape(pattern)}(?!${boundary})`,
    caseSensitive ? "" : "i",
  ).test(text);
}

/**
 * The technologies this topic's rows actually name, most-mentioned first.
 * Returns `[]` when the asks are capability-level ("build AI agents") rather
 * than product-level — saying nothing is the honest answer there.
 */
export function groundedTech(specifics: SpecificRequirement[], limit = 3): string[] {
  const scored: { display: string; hits: number; order: number }[] = [];

  LEXICON.forEach((term, order) => {
    const hits = specifics.filter((row) =>
      term.patterns.some((pattern) => mentions(row.text, pattern, term.caseSensitive)),
    ).length;
    if (hits > 0) scored.push({ display: term.display, hits, order });
  });

  return scored
    .sort((a, b) => b.hits - a.hits || a.order - b.order)
    .slice(0, limit)
    .map((term) => term.display);
}
