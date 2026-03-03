# Scopus IF Proxy Dashboard (Streamlit)

A Streamlit dashboard that computes a **Scopus-derived 2-year “impact factor” proxy** for any journal.

## What it computes

**JIF-like proxy (default):**

- **Numerator:** citations received in year **Y** to items published in **Y-1** and **Y-2** (from Scopus Citation Overview API)
- **Denominator:** number of citable items published in **Y-1** and **Y-2** (default: DOCTYPE **ar** + **re**)

You can switch to a symmetric proxy where numerator and denominator use the same document types.

## Requirements

- A Scopus API key (`SCOPUS_API_KEY`)
- Access to **Citation Overview API** (some keys require explicit entitlement)

## Local run

```bash
pip install -r requirements.txt
export SCOPUS_API_KEY="YOUR_KEY"
# optional:
export SCOPUS_INSTTOKEN="YOUR_INSTTOKEN"
streamlit run app.py
```

## Streamlit Cloud

Add secrets in the app settings:

- `SCOPUS_API_KEY`
- `SCOPUS_INSTTOKEN` (optional)

## Notes

- Citation Overview accepts **up to 25 identifiers per request**. Large journals may need many batched requests.
- Scopus Search offers a `cursor` parameter for deep pagination, but some API keys return an **ENTITLEMENTS_ERROR** saying its use is restricted. In that case, the app falls back to `start` pagination.
- Without cursor pagination, Scopus Search iteration is limited to **5,000 results per query**.
- Results will differ from Clarivate’s JIF; this is a proxy computed from Scopus data.
