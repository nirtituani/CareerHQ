/**
 * Grounded technology extraction (advisor-tech).
 *
 * The fixtures below are the **real requirement rows** from the deployed
 * account, verbatim. A change that breaks these breaks the feature on the only
 * data it has ever run against.
 *
 * The property under test is grounding, not recall: a term may appear only
 * because a row literally contains it.
 */

import { describe, expect, it } from "vitest";

import { groundedTech } from "@/lib/advisor-tech";
import type { SpecificRequirement } from "@/lib/api";

function rows(...texts: string[]): SpecificRequirement[] {
  return texts.map((text, index) => ({
    requirement_id: `req-${index}`,
    text,
    verdict: "gap" as const,
    shortfall: "capability" as const,
    importance: 50,
    profile_quote: null,
    resolved: true,
  }));
}

// -- the real production rows ------------------------------------------------

const CLOUD = rows(
  "Deep understanding of cloud infrastructure (AWS/GCP), containerization (Docker, Kubernetes), and networking",
  "Experience with cloud platforms and products (e.g. AWS, GCP and Azure)",
  "Experience with cloud environments (GCP preferred) and data tooling (SQL / BigQuery a plus).",
  "Experience with distributed cloud products and major cloud platforms (e.g., GCP, AWS, Azure).",
);

const CONTAINERS = rows(
  "Experience with Docker and microservices architectures",
  "Experience with containerization and orchestration technologies such as Kubernetes and Docker.",
);

const DATABASE = rows(
  "Hands-on experience with both relational databases (e.g., PostgreSQL) and NoSQL/caching solutions",
  "Strong experience with relational databases (PostgreSQL / SQLAlchemy) and automated testing (pytest)",
  "Proficiency with a variety of database technologies.",
  "Experience working with SQL databases",
);

const AI = rows(
  "Practical, hands-on experience with AI, demonstrated by using AI tools in your day-to-day coding",
  "Hands-on production experience with AI agent systems - a strong advantage",
  "Designing and building AI agents — orchestration, tool/function calling, memory and integration",
);

describe("groundedTech on the real production rows", () => {
  it("names the cloud platforms the postings actually asked for", () => {
    // Azure IS grounded here — two rows name it. Frequency ranking puts the
    // platforms the topic is about above the one-off Docker mention.
    expect(groundedTech(CLOUD)).toEqual(["GCP", "AWS", "Azure"]);
  });

  it("names Docker and Kubernetes for the containerisation topic", () => {
    expect(groundedTech(CONTAINERS)).toEqual(["Docker", "Kubernetes"]);
  });

  it("leads with the database the postings name most", () => {
    expect(groundedTech(DATABASE)[0]).toBe("PostgreSQL");
    expect(groundedTech(DATABASE)).toContain("SQLAlchemy");
  });

  it("says nothing when the asks are capability-level, not product-level", () => {
    // "build AI agents", "tool/function calling" name no product.
    expect(groundedTech(AI)).toEqual([]);
  });
});

describe("grounding — a term appears only if a row contains it", () => {
  it("never shows a cloud the evidence does not name", () => {
    const awsOnly = rows("Experience with cloud platforms such as AWS");
    const tech = groundedTech(awsOnly);
    expect(tech).toEqual(["AWS"]);
    expect(tech).not.toContain("Azure");
    expect(tech).not.toContain("GCP");
  });

  it("does not infer anything from a topic-shaped sentence with no products", () => {
    expect(groundedTech(rows("Experience with cloud platforms and products"))).toEqual([]);
    expect(groundedTech(rows("Proficiency with a variety of database technologies."))).toEqual([]);
  });

  it("returns nothing for an empty or unresolved topic", () => {
    expect(groundedTech([])).toEqual([]);
  });
});

describe("word boundaries", () => {
  it("does not match SQL inside PostgreSQL, SQLAlchemy or NoSQL", () => {
    expect(groundedTech(rows("Strong PostgreSQL and SQLAlchemy experience"))).not.toContain("SQL");
    expect(groundedTech(rows("NoSQL stores"))).not.toContain("SQL");
    expect(groundedTech(rows("Experience working with SQL databases"))).toContain("SQL");
  });

  it("matches a product named mid-sentence and in a parenthetical", () => {
    expect(groundedTech(rows("stack is Python/FastAPI"))).toEqual(
      expect.arrayContaining(["Python", "FastAPI"]),
    );
    expect(groundedTech(rows("containers (Docker)"))).toContain("Docker");
  });

  it("does not fire on a substring of an unrelated word", () => {
    // "Javascript-free" would still be JavaScript; "Javanese" must not be Java.
    expect(groundedTech(rows("Javanese literature"))).not.toContain("Java");
    expect(groundedTech(rows("reactive systems"))).not.toContain("React");
  });
});

describe("ranking and limit", () => {
  it("ranks by how many rows mention the term, then by lexicon order", () => {
    const mixed = rows(
      "Docker and Kubernetes",
      "Docker only",
      "Kubernetes and Terraform",
      "Docker again",
    );
    expect(groundedTech(mixed)).toEqual(["Docker", "Kubernetes", "Terraform"]);
  });

  it("caps the compact card at three terms by default", () => {
    expect(groundedTech(CLOUD).length).toBeLessThanOrEqual(3);
    expect(groundedTech(CLOUD, 2)).toEqual(["GCP", "AWS"]);
  });

  it("is deterministic across calls", () => {
    expect(groundedTech(CLOUD)).toEqual(groundedTech(CLOUD));
  });
});

describe("ordinary English is not a technology (regression)", () => {
  // Each of these produced a tag on the reviewed implementation, because the
  // matcher was case-insensitive and several lexicon entries are common words.
  // The module's stated invariant is that a technology absent from the evidence
  // can never be shown at all.
  it.each([
    ["Ability to work at a swift pace and deliver", "Swift"],
    ["Comfortable taking the helm of a squad", "Helm"],
    ["Bring a spark of creativity to the team", "Spark"],
    ["Ability to react quickly to production incidents", "React"],
    ["A rusty grasp of systems programming is fine", "Rust"],
    ["Spring 2026 internship cohort", "Spring"],
    ["Experience with RAG status reporting to stakeholders", "RAG"],
    ["Familiar with lambda expressions and closures", "Serverless"],
    ["Familiar with lambda expressions and closures", "AWS Lambda"],
  ])("does not tag %j as %s", (text, tag) => {
    expect(groundedTech(rows(text))).not.toContain(tag);
  });

  it("shows nothing at all for a row of pure prose", () => {
    expect(groundedTech(rows("Comfortable taking the helm at a swift pace, sparking ideas"))).toEqual(
      [],
    );
  });
});

describe("the real product is still recognised (the other half of the trade)", () => {
  it.each([
    ["Swift and Kotlin for the mobile client", "Swift"],
    ["Author Helm charts for each service", "Helm"],
    ["Apache Spark batch pipelines", "Spark"],
    ["React and TypeScript on the front end", "React"],
    ["Rust for the ingestion hot path", "Rust"],
    ["Spring Boot microservices", "Spring"],
    ["Build retrieval-augmented generation pipelines", "RAG"],
    ["AWS Lambda behind API Gateway", "AWS Lambda"],
    ["Serverless architecture on AWS", "Serverless"],
  ])("tags %j as %s", (text, tag) => {
    expect(groundedTech(rows(text))).toContain(tag);
  });
});
