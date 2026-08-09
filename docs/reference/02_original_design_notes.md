# Original Design Notes

> The author's own design thinking, written in Hebrew before the English design documents existed,
> reproduced verbatim. Preserved because the English docs are an *interpretation* of it — when
> checking whether the implementation still reflects the original intent, this is the source.
>
> Where each idea ended up is mapped at the bottom.

---

## המבנה המומלץ

### 1. Resume Optimizer Agent

התפקיד שלו יהיה:

- לנתח תיאור משרה
- להשוות מול קורות החיים
- לתת Match Score
- לזהות פערים ומילות מפתח חסרות
- להציע שינויים ב-Summary, Skills ובניסיון
- ליצור גרסה מותאמת למשרה
- להעביר את התוצאה ל-Reviewer לפני אישור

כאן אפשר להשתמש ב-Workflow של:

```
Analyze → Retrieve Guidelines → Draft → Self-Critique → Revise
```

### 2. Company Research Agent

כן, הייתי מכניס אותו כבר בשלב הזה, אבל ב-Scope מוגבל.

הוא יכול לאסוף ולסכם:

- מה החברה עושה
- המוצר והלקוחות
- התחום והמתחרים
- טכנולוגיות שמופיעות במקורות ציבוריים
- מידע רלוונטי להכנה לראיון
- נושאים שכדאי ללמוד לפני הפנייה
- שאלות חכמות שאפשר לשאול בראיון

כדאי שהוא יחזיר גם מקורות וציטוטים, ולא רק סיכום חופשי.

### 3. Application Manager

כרגע הוא מערכת רגילה של: CRUD, סטטוסים, מעקב, תאריכים, Analytics.

וזה מצוין. **לא כל חלק במוצר צריך להיות Agent.**

הוא יהפוך ל-Agentic רק אם תוסיף לו יכולת לפעול באופן יזום, למשל:

- לזהות שמשרה נמצאת זמן רב בלי תגובה
- להציע Follow-up
- לזהות Deadline מתקרב
- להמליץ על הפעולה הבאה
- לעדכן רשומה אוטומטית לאחר אישור המשתמש
- לזהות מידע חסר בהגשה
- להפעיל Agent אחר לפי מצב ההגשה

לכן הייתי קורא לו **Application Management Core**, ומעליו אפשר לבנות **Application Workflow
Agent**. ה-Core שומר ומציג מידע. ה-Agent מנתח מצב ומציע או מבצע פעולות.

### 4. Career Advisor Agent

- ניתוח מצטבר של כל המשרות שאליהן הגשת
- זיהוי Skills שחוזרים שוב ושוב בדרישות
- הבחנה בין פער קריטי לבין Nice-to-have
- זיהוי תחומי תפקיד שבהם ההתאמה שלך גבוהה יותר
- המלצה מה ללמוד קודם לפי שכיחות והשפעה
- יצירת Learning Roadmap קצר
- מעקב אם הפערים מצטמצמים לאורך זמן

לדוגמה:

```
Python הופיע ב-14 מתוך 20 משרות
Kubernetes הופיע ב-9 מתוך 20
Java הופיע ב-4 בלבד
לכן ההמלצה: להשקיע קודם ב-Python async וב-Kubernetes בסיסי
```

זה Agent עם ערך אמיתי, כי הוא מסיק מסקנות מזיכרון מצטבר ולא רק עונה על Prompt יחיד.

### 5. Interview Preparation Agent

בשלב הראשון הוא לא צריך "ללמד" אותך. הוא יכול:

- לזהות נושאים מקצועיים שעלולים לעלות בראיון
- להפיק שאלות צפויות לפי המשרה
- להמליץ על מקורות לימוד
- להכין Checklist
- ליצור תוכנית הכנה לפי זמן שנותר
- לקשר בין דרישות המשרה לניסיון שלך
- להציע סיפורי ניסיון שכדאי להכין
- להכין Company-specific briefing

הוא גם יכול להשתמש בתוצאות של Company Research Agent.

### 6. Evaluation / Reviewer Agent

> רק רכיב אחד שאני חושב שהוא חשוב מאוד.

לא חייבים להציג אותו כ-Agent עצמאי בממשק, אבל הוא חשוב מאחורי הקלעים.

התפקיד שלו:

- לבדוק אם קורות החיים באמת מבוססים על מידע קיים
- לזהות ניסוחים מוגזמים
- לבדוק אם התוצאה מכסה את דרישות המשרה
- לבדוק עקביות בין Resume, Job Description ו-User Profile
- לתת Confidence Score
- לבקש תיקון מה-Agent הראשי במקרה הצורך

כך אתה מדגים: Self-critique, Quality control, Reliability, Evaluation, Guardrails.

---

## הארכיטקטורה ברמה גבוהה

```
Application Management Core
        |
        +-- Resume Optimizer Agent
        +-- Company Research Agent
        +-- Career Advisor Agent
        +-- Interview Preparation Agent
        +-- Application Workflow Agent
        +-- Evaluation / Reviewer Layer
```

Workflow עבור משרה חדשה:

```
Add Job → Analyze Job Description → Research Company → Calculate Match & Gaps
→ Tailor Resume → Review & Validate → Save Resume Version
→ Generate Interview Prep Plan → Track Application
```

> לא חייבים שכל חמשת ה-Agents יהיו מושלמים בגרסה הראשונה; **עדיף שניים עמוקים ומערכת עובדת מאשר
> חמישה דקים.**

---

## מודל הגרסאות

במקום מערכת שבה כל גרסה "יורשת" עדכונים מה-Master, עדיף מודל של:

```
Master Resume
   ├── Backend Master
   └── AI Backend Master
```

ומתוך כל Master נוצרת גרסה קפואה למשרה:

```
Backend Master              AI Backend Master
   ├── Upwind — Frozen         ├── OriginAI — Frozen
   ├── Zipher — Frozen         ├── Gloat — Frozen
   └── DriveNets — Frozen      └── Voyantis — Frozen
```

### איך זה יעבוד בפועל

1. בוחר Master מתאים
2. משכפל אותו לגרסה ייעודית למשרה
3. מפעיל התאמה אוטומטית
4. בודק Diff ומאשר שינויים
5. מייצא PDF
6. מסמן את הגרסה כ-Submitted / Locked

מרגע שנשלחה: לא משתנה אוטומטית, לא מושפעת מעדכונים ב-Master, נשמרת כהיסטוריה מדויקת של מה שנשלח.
אפשר לצפות בה ולהוריד אותה שוב. אפשר ליצור ממנה עותק חדש, אבל לא לשנות את המקור.

### למה זה עדיף

כך המערכת שומרת אמת היסטורית: איזה קו״ח נשלחו, לאיזו חברה ומשרה, מתי נשלחו, מה היה Match Score
באותו זמן, אילו שינויים אושרו, איזה PDF בדיוק יצא.

זה גם חשוב ל-Career Advisor, כי הוא יוכל לנתח בדיעבד אילו גרסאות הובילו לראיונות.

### סטטוסים

```
Draft → Ready → Exported → Submitted → Locked
```

בפועל, אפשר לאחד Submitted ו-Locked: ברגע שהמשתמש מסמן שהגיש, הגרסה ננעלת.

### עדכון Master

כאשר תלמד טכנולוגיה חדשה או תוסיף ניסיון: מעדכנים רק את ה-Master המתאים. גרסאות ישנות נשארות ללא
שינוי. משרות חדשות מתחילות מה-Master המעודכן.

המערכת יכולה להציע:

> "נוסף FastAPI ל-AI Backend Master. להשתמש בגרסה המעודכנת למשרה הבאה?"

אבל לא לעדכן אף גרסה שכבר הוגשה.

### מסקנה ארכיטקטונית

לא נבנה Inheritance חי, אלא **Template lineage + immutable snapshots**. כל גרסה שומרת מאיזה Master
נוצרה, אבל לאחר השכפול היא מסמך עצמאי.

---

## Where each idea ended up

| Original idea | Landed in |
|---|---|
| Resume Optimizer with `Analyze → Retrieve → Draft → Self-Critique → Revise` | `docs/07` §3.2, `docs/01` §8, slice 004 |
| Company Research returning sources and citations | `docs/07` §3.4, slice 006 |
| Application Manager as deterministic Core, not an agent | Constitution Principle V, `docs/07` §3.1 |
| Application Workflow Agent (proactive) | `docs/01` §12 — deferred, first stretch goal |
| Career Advisor with skill frequency counting | `docs/07` §3.5, slice 007 |
| Interview Preparation Agent | `docs/07` §3.6 — deferred, second stretch goal |
| **Evaluation / Reviewer layer** | `docs/07` §3.3, AI-012–014, **slice 005** |
| Template lineage over live inheritance | **ADR-012** |
| Status lifecycle `Draft → Ready → Exported → Submitted` | FR-031, `docs/03` §10.1 |
| "Two deep agents beat five shallow ones" | `docs/05` §2, and the build priority in `docs/07` §6 |

The one idea from these notes that the English documents originally lost entirely was the
**Application Workflow Agent**; it is now recorded as deferred rather than forgotten. The
**Reviewer layer** was also briefly scoped out of the MVP before being restored as slice 005 —
recorded as correction 4 in `docs/05` §8.
