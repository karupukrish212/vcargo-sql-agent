"""Pick a chart from the shape of a result, without asking the LLM.

Vanna's own charting has the LLM write Python that the server executes; for a shared
API that is a code-execution risk, so charts are built here from the column types.
"""
import base64
import json
import re

import numpy as np
import pandas as pd
import plotly.express as px

_DATE_NAME = re.compile(r"date|month|day|week|year|time|period", re.IGNORECASE)
_MAX_BARS = 50
_MAX_SERIES = 5


def _is_time_axis(s: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    if not _DATE_NAME.search(str(s.name)) or pd.api.types.is_numeric_dtype(s):
        return False
    parsed = pd.to_datetime(s.astype(str), errors="coerce", format="mixed")
    return parsed.notna().all()


def _is_id(column: str) -> bool:
    return column.lower().endswith("id")


def build_chart(df: pd.DataFrame) -> dict | None:
    """Plotly figure as JSON ({data, layout}) for react-plotly.js, or None if a chart doesn't help."""
    if df.empty or len(df.columns) < 2:
        return None
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not _is_id(c)]
    if not numeric:
        return None
    others = [c for c in df.columns if c not in numeric and not _is_id(c)]
    if not others:
        # e.g. "profit by trip": the id is the only label, so use it as a category
        others = [c for c in df.columns if _is_id(c)]
    time_cols = [c for c in others if _is_time_axis(df[c])]

    if time_cols:
        x = time_cols[0]
        ys = [c for c in numeric if c != x][:_MAX_SERIES]
        data = df.sort_values(x)
        fig = px.line(data, x=x, y=ys, markers=True)
    elif others and len(df) > 1:
        x = others[0]
        ys = numeric[:_MAX_SERIES]
        fig = px.bar(df.head(_MAX_BARS), x=x, y=ys, barmode="group")
        # Labels are categories even when numeric (ids, codes); otherwise bars land on a number line
        fig.update_xaxes(type="category")
    else:
        return None

    fig.update_layout(legend_title_text="", margin=dict(l=40, r=20, t=30, b=40))
    if len(ys) == 1:
        fig.update_layout(yaxis_title=ys[0], showlegend=False)
    return _plain_arrays(json.loads(fig.to_json()))


def _plain_arrays(node):
    """Plotly 7 packs arrays as {"dtype", "bdata": base64}; older plotly.js and anyone
    reading the numbers directly need plain JSON lists."""
    if isinstance(node, dict):
        if "bdata" in node and "dtype" in node:
            values = np.frombuffer(base64.b64decode(node["bdata"]), dtype=node["dtype"])
            if "shape" in node:
                values = values.reshape([int(n) for n in str(node["shape"]).split(",")])
            return values.tolist()
        return {k: _plain_arrays(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain_arrays(v) for v in node]
    return node
