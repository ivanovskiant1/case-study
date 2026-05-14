"""Evaluation harness: runs all 7 sample briefs through the agent and prints traces.

For briefs with missing info, supplies a follow-up answer and continues so we see
the final recommendation in every case.
"""
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

from app.agent import MediaAgent  # noqa: E402

ROOT = Path(__file__).resolve().parent
BRIEFS = json.loads((ROOT / "client_briefs.json").read_text())

# Hand-authored follow-up answers for briefs that need them.
FOLLOWUPS = {
    5: "It's a Retail mobile app.",  # missing vertical
    6: "Click-through rate is the priority.",  # missing KPI
}


def run_brief(idx: int, brief: str) -> dict:
    agent = MediaAgent()
    transcript = [("user", brief)]
    reply = agent.chat(brief)
    transcript.append(("assistant", reply))

    if agent.brief.missing_required() and idx in FOLLOWUPS:
        followup = FOLLOWUPS[idx]
        transcript.append(("user", followup))
        reply2 = agent.chat(followup)
        transcript.append(("assistant", reply2))

    return {
        "idx": idx,
        "brief": brief,
        "transcript": transcript,
        "final_brief": agent.brief.model_dump(exclude_none=True),
        "missing": agent.brief.missing_required(),
        "recommendation": (
            agent.latest_recommendation.model_dump()
            if agent.latest_recommendation
            else None
        ),
    }


def main():
    results = []
    for i, brief in enumerate(BRIEFS):
        print(f"\n{'='*80}\nBRIEF {i}: {brief}\n{'='*80}")
        r = run_brief(i, brief)
        results.append(r)
        for role, text in r["transcript"]:
            print(f"\n[{role.upper()}]\n{text}")
        print(f"\n[FINAL BRIEF STATE]\n{json.dumps(r['final_brief'], indent=2)}")
        if r["missing"]:
            print(f"[STILL MISSING] {r['missing']}")
        if r["recommendation"]:
            rec = r["recommendation"]
            top = rec["recommended"][0] if rec["recommended"] else None
            if top:
                kpi = rec["brief"]["kpi"]
                kpi_val = top[f"benchmark_{kpi}"]
                print(
                    f"\n[RECOMMENDED] {top['product_name']} "
                    f"(CPM ${top['cpm']:.2f}, "
                    f"est {top['estimated_impressions']:,} imps, "
                    f"benchmark {kpi}={kpi_val:.4f}, "
                    f"risk-adj avail {top['risk_adjusted_impressions']:,}, "
                    f"meets_scale={top['meets_scale']}, "
                    f"meets_goal={top['meets_impression_goal']})"
                )
                if top["notes"]:
                    print(f"[NOTES] {top['notes']}")
            print(f"[RATIONALE] {rec['rationale']}")
            print(f"[REJECTED] {[o['product_name'] for o in rec['rejected']]}")

    # Save raw results for later analysis.
    (ROOT / "eval_results.json").write_text(
        json.dumps(results, indent=2, default=str)
    )
    print(f"\n\nSaved raw results to eval_results.json")


if __name__ == "__main__":
    main()
