# How eligibility verdicts work

Every job gets one of three verdicts for your profile, with the reasons in plain words:

- **Eligible**: something clear confirms you can apply, and nothing is left open.
- **Not eligible**: something clear rules it out (a listed country, a company you skip, a word you excluded).
- **Unclear**: anything else. Unclear is never shown as eligible, and nothing is hidden or deleted because of a verdict.

The rules are fixed and run on your machine. No AI is involved, so the same job and profile always give the same answer. (If you use an AI key, the AI score is a separate number about how well the job matches your CV.)

## What it checks

1. **Where the job can be done from.**
   - For remote jobs: the countries the source states (Remotive, Himalayas, Jobicy and Working Nomads publish a field for this), then phrases in the text such as "US only", "must be based in", "EMEA", "UTC+3".
   - For on-site and hybrid jobs: the city or country of the job against the countries you can work in without sponsorship.
   - A job outside those countries is not eligible unless it is in a country you listed for relocation. Then the listing's visa or relocation wording decides: it says it does not sponsor visas (not eligible), offers sponsorship or relocation (eligible), or says nothing (eligible if you do not need a visa, otherwise unclear).
2. **Your own rules.** Companies you skip, dealbreaker words, work modes you exclude, and a pay floor (only when the listing states pay in your currency).
3. **Time zones.** If you gave a maximum gap and the listing states a zone.
4. **Citizenship or security clearance wording** makes a job unclear, never not eligible.

Place names come from a built-in table of about 200 countries, 350 cities, US states, Canadian provinces and 18 regions (GCC, MENA, EMEA, EU, APAC and others), including Arabic names. Nothing is downloaded.

## Why a job is unclear

The reason says which. The common ones:

- It is located in a country you cannot work in, and the listing does not say whether it can be done remotely.
- It says remote but not which countries may apply.
- The source's location field and the text disagree (for example "on-site" in one place and "fully remote" in the other).
- It mentions clearance or citizenship.
- It has no location the table recognises, or your profile has no country yet.

## How accurate it is

On 70 real listings I labelled by hand for one profile (lives in the UAE, can work in the GCC), from Remotive, Remote OK and Arbeitnow:

| | |
|---|---|
| Same verdict as the hand label | 62 of 70 |
| Wrongly marked not eligible | 0 |
| Wrongly marked eligible | 0 |
| Marked unclear where the hand label was firm | 8 |

Read that with its limits: it is a small sample, I did the labelling, it is one profile, three sources, and I tuned the rules while looking at those listings, so the true error rate on new listings will be higher. The design leans cautious on purpose: when unsure it says unclear. A wrong "not eligible" is the costly error because it can hide a job you could have had, so that is the one to watch. If you find one, please open an issue with the listing and your profile settings.

On a larger run (23 Nov 2026: 4,628 listings, a UAE profile) the verdicts were about 5% eligible, 70% unclear and 25% not eligible. The large unclear share is mostly on-site jobs abroad whose listings do not say whether they can be done remotely.

## What it does not know

- It reads the listing's words. A listing that says "remote" and means "remote in the US" without saying so will read as unclear, not as wrong.
- Languages, seniority and visa wording are read from English text. Seniority is detected but does not change a verdict.
- It does not check that a job is still open, or that the employer will really sponsor you.
- Freshness labels (new, old, closed) are signals from dates and from what a source still lists. They are not a judgement that a job is real or fake.
