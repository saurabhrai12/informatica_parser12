# Contact Center Intelligence Dashboard — Program Specification

## Document Metadata

| Field | Value |
|---|---|
| Version | 1.0 |
| Author | Saurabh |
| Stack | Python · Plotly Dash · Snowflake |
| Data Source | Genesys Cloud → Snowflake (Cortex AI enriched) |
| Last Updated | April 2026 |

---

## 1. Project Overview

### 1.1 Purpose

Build a production-grade, interactive Contact Center Intelligence Dashboard that surfaces AI-enriched call analytics from Genesys Cloud data stored in Snowflake. The dashboard enables operations leaders to understand call volume patterns, sentiment trends, resolution effectiveness, and team performance through four purpose-built analytical views.

### 1.2 Architecture Summary

```
Genesys Cloud API
    │
    ▼
Snowflake (Raw Ingestion)
    │
    ├── Cortex LLM  → AI Summary, Categorization, Resolution Steps
    ├── Cortex LLM  → Sentiment Scoring (per-call + intra-call trajectory)
    ├── Cortex LLM  → Outcome Classification (resolved/unresolved/callback/escalated)
    │
    ▼
Snowflake Analytics Tables
    │
    ▼
Python (Plotly Dash Application)
    │
    ├── Tab 1: Executive Overview
    ├── Tab 2: Category Deep Dive
    ├── Tab 3: Team Performance
    └── Tab 4: Call Explorer
```

### 1.3 Tech Stack

| Component | Technology |
|---|---|
| Backend / App Server | Python 3.11+, Plotly Dash 2.x |
| Visualization | Plotly Graph Objects + Plotly Express |
| Data Layer | Snowflake Connector for Python, Pandas |
| Caching | Flask-Caching (Redis or filesystem) |
| Styling | Dash Bootstrap Components, custom CSS |
| Deployment | Docker container or Snowflake Streamlit (optional) |

---

## 2. Data Model

### 2.1 Source Tables in Snowflake

#### `FACT_CALLS` — Primary call-level fact table

| Column | Type | Description |
|---|---|---|
| CALL_ID | VARCHAR | Unique Genesys conversation ID |
| CALL_START_TS | TIMESTAMP_NTZ | Call start timestamp |
| CALL_END_TS | TIMESTAMP_NTZ | Call end timestamp |
| HANDLE_TIME_SEC | NUMBER | Total handle time in seconds |
| QUEUE_NAME | VARCHAR | Genesys queue (e.g., General, Priority, VIP, Technical, Escalation) |
| DIVISION_NAME | VARCHAR | Genesys division (e.g., North, South, East, West) |
| AGENT_ID | VARCHAR | Agent identifier |
| TEAM_NAME | VARCHAR | Team/group the agent belongs to |
| TRANSCRIPT_TEXT | VARCHAR | Full call transcript |
| AI_SUMMARY | VARCHAR | Cortex LLM-generated call summary |
| AI_CATEGORY | VARCHAR | Cortex LLM-assigned category (Billing, Tech Support, Account Access, Service Outage, New Service, Complaints) |
| AI_SENTIMENT_SCORE | FLOAT | Sentiment score 0.0 (very negative) to 1.0 (very positive) |
| AI_SENTIMENT_LABEL | VARCHAR | Positive / Neutral / Negative |
| AI_OUTCOME | VARCHAR | Resolved / Unresolved / Callback / Escalated |
| AI_RESOLUTION_STEPS | VARCHAR | Pipe-delimited resolution steps (e.g., "Router reset \| DNS flush \| Speed test \| Confirmed") |
| AI_SENTIMENT_START | FLOAT | Sentiment score for first 25% of transcript |
| AI_SENTIMENT_END | FLOAT | Sentiment score for last 25% of transcript |
| IS_REPEAT_CALLER | BOOLEAN | True if same customer called within 72 hours on same category |
| CREATED_AT | TIMESTAMP_NTZ | Record creation timestamp |

#### `DIM_TEAMS` — Team dimension

| Column | Type | Description |
|---|---|---|
| TEAM_NAME | VARCHAR | Team identifier (Alpha, Beta, Gamma, Delta) |
| DIVISION_NAME | VARCHAR | Division the team operates under |
| TEAM_LEAD | VARCHAR | Team lead name |
| HEADCOUNT | NUMBER | Number of agents |

#### `DIM_QUEUES` — Queue dimension

| Column | Type | Description |
|---|---|---|
| QUEUE_NAME | VARCHAR | Queue name |
| PRIORITY_LEVEL | NUMBER | 1 (lowest) to 5 (highest) |
| SLA_TARGET_SEC | NUMBER | Target handle time in seconds |

### 2.2 Pre-Aggregated Views (for dashboard performance)

#### `AGG_DAILY_METRICS`

```sql
CREATE OR REPLACE VIEW AGG_DAILY_METRICS AS
SELECT
    DATE_TRUNC('day', CALL_START_TS)          AS CALL_DATE,
    AI_CATEGORY,
    TEAM_NAME,
    QUEUE_NAME,
    DIVISION_NAME,
    COUNT(*)                                   AS CALL_COUNT,
    AVG(HANDLE_TIME_SEC)                       AS AVG_HANDLE_TIME_SEC,
    AVG(AI_SENTIMENT_SCORE)                    AS AVG_SENTIMENT,
    SUM(CASE WHEN AI_OUTCOME = 'Resolved' THEN 1 ELSE 0 END)::FLOAT
        / NULLIF(COUNT(*), 0) * 100            AS RESOLUTION_RATE,
    SUM(CASE WHEN AI_OUTCOME = 'Callback' THEN 1 ELSE 0 END)::FLOAT
        / NULLIF(COUNT(*), 0) * 100            AS CALLBACK_RATE,
    SUM(CASE WHEN AI_OUTCOME = 'Escalated' THEN 1 ELSE 0 END)::FLOAT
        / NULLIF(COUNT(*), 0) * 100            AS ESCALATION_RATE,
    SUM(CASE WHEN AI_SENTIMENT_LABEL = 'Negative' THEN 1 ELSE 0 END)::FLOAT
        / NULLIF(COUNT(*), 0) * 100            AS NEGATIVE_SENTIMENT_PCT,
    SUM(CASE WHEN AI_SENTIMENT_LABEL = 'Positive' THEN 1 ELSE 0 END)::FLOAT
        / NULLIF(COUNT(*), 0) * 100            AS POSITIVE_SENTIMENT_PCT,
    SUM(CASE WHEN IS_REPEAT_CALLER THEN 1 ELSE 0 END) AS REPEAT_CALLER_COUNT
FROM FACT_CALLS
GROUP BY 1, 2, 3, 4, 5;
```

#### `AGG_WEEKLY_METRICS`

Same structure as daily, with `DATE_TRUNC('week', CALL_START_TS)` for trend charts.

---

## 3. Application Structure

### 3.1 Project Layout

```
contact_center_dashboard/
├── app.py                     # Main Dash application entry point
├── config.py                  # Snowflake connection, app settings
├── requirements.txt
├── Dockerfile
│
├── data/
│   ├── snowflake_connector.py # Connection pool, query execution
│   ├── queries.py             # All SQL queries as named constants
│   └── cache.py               # Caching layer
│
├── layouts/
│   ├── header.py              # Top header with KPIs and period selector
│   ├── tab_overview.py        # Tab 1: Executive Overview
│   ├── tab_categories.py      # Tab 2: Category Deep Dive
│   ├── tab_teams.py           # Tab 3: Team Performance
│   └── tab_calls.py           # Tab 4: Call Explorer
│
├── charts/
│   ├── kpi_cards.py           # KPI card components
│   ├── treemap.py             # Category volume treemap
│   ├── volume_sentiment.py    # Dual-axis volume + sentiment
│   ├── resolution_trend.py    # Resolution & callback line chart
│   ├── scatter_priority.py    # Priority quadrant bubble chart
│   ├── sankey_flow.py         # Category → outcome Sankey
│   ├── diverging_bar.py       # Sentiment diverging bars
│   ├── heatmap_outcome.py     # Outcome × category heatmap
│   ├── stacked_area.py        # Category volume stacked area
│   ├── dot_plot_aht.py        # AHT dot/dumbbell plot
│   ├── team_bars.py           # Team performance horizontal bars
│   ├── team_heatmap.py        # Multi-metric team heatmap
│   └── call_table.py          # Interactive call explorer table
│
├── callbacks/
│   ├── filters.py             # Global filter callbacks (period, division, queue)
│   ├── tab_routing.py         # Tab switching logic
│   └── drill_down.py          # Cross-chart drill-down callbacks
│
└── assets/
    ├── style.css              # Custom dashboard styling
    └── favicon.ico
```

### 3.2 Global Filters (Applied Across All Tabs)

| Filter | Type | Default | Values |
|---|---|---|---|
| Time Period | Button Group | 7D | 24H, 7D, 30D, 90D, Custom |
| Division | Multi-Select Dropdown | All | North, South, East, West |
| Queue | Multi-Select Dropdown | All | General, Priority, VIP, Technical, Escalation |
| Category | Multi-Select Dropdown | All | All AI categories |
| Team | Multi-Select Dropdown | All | Alpha, Beta, Gamma, Delta |

All filters propagate to every chart via Dash callbacks using a shared `dcc.Store` component.

---

## 4. Tab Specifications

---

### 4.1 TAB 1 — Executive Overview

**Purpose:** At-a-glance operational health. Answer: "How is the contact center performing right now?"

---

#### 4.1.1 KPI Cards (Top Row)

**Component:** 5 × `dash_bootstrap_components.Card` with inline sparkline

| KPI | Metric SQL | Format | Sparkline | Color |
|---|---|---|---|---|
| Total Calls | `SUM(CALL_COUNT)` | `12,847` | 7-day daily trend | Blue `#3B82F6` |
| Resolution Rate | `AVG(RESOLUTION_RATE)` | `78.4%` | 7-day daily trend | Green `#10B981` |
| Avg Handle Time | `AVG(AVG_HANDLE_TIME_SEC) / 60` | `6:42` | 7-day daily trend | Cyan `#06B6D4` |
| Avg Sentiment | `AVG(AVG_SENTIMENT)` | `0.62` | 7-day daily trend | Amber `#F59E0B` |
| Callback Rate | `AVG(CALLBACK_RATE)` | `14.2%` | 7-day daily trend | Red `#EF4444` |

Each card shows:
- Current period value (large)
- Delta vs. previous period (arrow + percentage)
- Mini sparkline (Plotly `go.Scatter` with `fill='tozeroy'`, no axes, height=40px)

**Sparkline Implementation:**

```python
fig = go.Figure(go.Scatter(
    x=dates, y=values,
    mode='lines',
    fill='tozeroy',
    line=dict(color=card_color, width=2),
    fillcolor=f'rgba({r},{g},{b},0.1)'
))
fig.update_layout(
    margin=dict(l=0, r=0, t=0, b=0),
    height=40, width=120,
    xaxis=dict(visible=False),
    yaxis=dict(visible=False),
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)'
)
```

---

#### 4.1.2 Call Volume & Sentiment Trend (Dual-Axis Combo)

**Chart Type:** `plotly.graph_objects` — Bar + Line combo with secondary Y-axis

**Purpose:** Correlate volume spikes with sentiment drops to identify stress periods.

| Attribute | Mapping |
|---|---|
| X-Axis | `CALL_WEEK` (weekly buckets from `AGG_WEEKLY_METRICS`) |
| Y-Axis (Left) | `SUM(CALL_COUNT)` — displayed as bars |
| Y-Axis (Right) | `AVG(AVG_SENTIMENT)` — displayed as line with markers |
| Bar Color | `rgba(59, 130, 246, 0.4)` with border `#3B82F6` |
| Line Color | `#F59E0B` (amber) |
| Tooltip | Week, Volume count, Sentiment score, Delta vs prev week |

```python
fig = make_subplots(specs=[[{"secondary_y": True}]])

fig.add_trace(go.Bar(
    x=df['CALL_WEEK'],
    y=df['TOTAL_VOLUME'],
    name='Call Volume',
    marker=dict(color='rgba(59,130,246,0.4)', line=dict(color='#3B82F6', width=1)),
    hovertemplate='Week: %{x}<br>Volume: %{y:,}<extra></extra>'
), secondary_y=False)

fig.add_trace(go.Scatter(
    x=df['CALL_WEEK'],
    y=df['AVG_SENTIMENT'],
    name='Avg Sentiment',
    mode='lines+markers',
    line=dict(color='#F59E0B', width=2.5),
    marker=dict(size=7, color='#F59E0B'),
    fill='tozeroy',
    fillcolor='rgba(245,158,11,0.08)',
    hovertemplate='Week: %{x}<br>Sentiment: %{y:.2f}<extra></extra>'
), secondary_y=True)

fig.update_yaxes(title_text="Call Volume", secondary_y=False, gridcolor='rgba(30,41,59,0.5)')
fig.update_yaxes(title_text="Avg Sentiment", secondary_y=True, range=[0, 1], gridcolor='rgba(0,0,0,0)')
```

**SQL:**

```sql
SELECT
    DATE_TRUNC('week', CALL_DATE) AS CALL_WEEK,
    SUM(CALL_COUNT)               AS TOTAL_VOLUME,
    AVG(AVG_SENTIMENT)            AS AVG_SENTIMENT
FROM AGG_DAILY_METRICS
WHERE CALL_DATE >= :start_date AND CALL_DATE <= :end_date
GROUP BY 1
ORDER BY 1;
```

---

#### 4.1.3 Resolution & Callback Trend

**Chart Type:** `go.Scatter` — Dual line chart

**Purpose:** Track operational improvement over time.

| Attribute | Mapping |
|---|---|
| X-Axis | `CALL_WEEK` |
| Line 1 | `AVG(RESOLUTION_RATE)` — Green `#10B981` |
| Line 2 | `AVG(CALLBACK_RATE)` — Red `#EF4444` |
| Y-Axis | Percentage (0–100%) |
| Fill | `tozeroy` with low opacity |
| Annotations | Target line at 85% resolution (dashed) |

```python
fig.add_trace(go.Scatter(
    x=df['CALL_WEEK'], y=df['RESOLUTION_RATE'],
    name='Resolution %', mode='lines+markers',
    line=dict(color='#10B981', width=2.5),
    fill='tozeroy', fillcolor='rgba(16,185,129,0.08)'
))
fig.add_trace(go.Scatter(
    x=df['CALL_WEEK'], y=df['CALLBACK_RATE'],
    name='Callback %', mode='lines+markers',
    line=dict(color='#EF4444', width=2.5),
    fill='tozeroy', fillcolor='rgba(239,68,68,0.06)'
))
# Target line
fig.add_hline(y=85, line_dash="dash", line_color="#10B981",
              opacity=0.4, annotation_text="Target: 85%")
```

---

#### 4.1.4 Category Volume Treemap

**Chart Type:** `px.treemap`

**Purpose:** Instantly show which call categories dominate volume through proportional area.

| Attribute | Mapping |
|---|---|
| Path | `[AI_CATEGORY]` |
| Values | `SUM(CALL_COUNT)` |
| Color | `AVG(AVG_SENTIMENT)` (continuous scale — red-to-green) |
| Color Scale | `RdYlGn` (red = low sentiment, green = high) |
| Text | Category name + volume count + percentage of total |
| Hover | Category, Volume, % of total, Avg sentiment, Resolution rate |

```python
fig = px.treemap(
    df,
    path=['AI_CATEGORY'],
    values='TOTAL_VOLUME',
    color='AVG_SENTIMENT',
    color_continuous_scale='RdYlGn',
    color_continuous_midpoint=0.5,
    hover_data={
        'TOTAL_VOLUME': ':,',
        'AVG_SENTIMENT': ':.2f',
        'RESOLUTION_RATE': ':.1f'
    }
)
fig.update_traces(
    textinfo='label+value+percent root',
    textfont=dict(size=14, family='DM Sans'),
    hovertemplate=(
        '<b>%{label}</b><br>'
        'Volume: %{value:,}<br>'
        'Sentiment: %{color:.2f}<br>'
        '<extra></extra>'
    )
)
```

**SQL:**

```sql
SELECT
    AI_CATEGORY,
    SUM(CALL_COUNT)          AS TOTAL_VOLUME,
    AVG(AVG_SENTIMENT)       AS AVG_SENTIMENT,
    AVG(RESOLUTION_RATE)     AS RESOLUTION_RATE
FROM AGG_DAILY_METRICS
WHERE CALL_DATE >= :start_date AND CALL_DATE <= :end_date
GROUP BY 1;
```

---

#### 4.1.5 Priority Quadrant — Bubble Scatter

**Chart Type:** `go.Scatter` (bubble mode)

**Purpose:** Identify which categories need urgent attention. Top-right quadrant = high AHT + high negative sentiment + high volume = ACT NOW.

| Attribute | Mapping |
|---|---|
| X-Axis | `AVG(AVG_HANDLE_TIME_SEC) / 60` — Avg Handle Time (minutes) |
| Y-Axis | `AVG(NEGATIVE_SENTIMENT_PCT)` — Negative Sentiment % |
| Bubble Size | `SUM(CALL_COUNT)` — proportional to volume |
| Bubble Color | Per-category color from defined palette |
| Text Labels | Category name on each bubble |
| Quadrant Lines | Median AHT (vertical) + Median Neg% (horizontal) as dashed reference |

```python
fig = go.Figure()

for i, row in df.iterrows():
    fig.add_trace(go.Scatter(
        x=[row['AVG_AHT_MIN']],
        y=[row['NEGATIVE_SENTIMENT_PCT']],
        mode='markers+text',
        marker=dict(
            size=row['TOTAL_VOLUME'] / scale_factor,
            color=category_colors[row['AI_CATEGORY']],
            opacity=0.7,
            line=dict(width=2, color=category_colors[row['AI_CATEGORY']])
        ),
        text=row['AI_CATEGORY'],
        textposition='top center',
        name=row['AI_CATEGORY'],
        hovertemplate=(
            f"<b>{row['AI_CATEGORY']}</b><br>"
            f"AHT: {row['AVG_AHT_MIN']:.1f} min<br>"
            f"Negative: {row['NEGATIVE_SENTIMENT_PCT']:.1f}%<br>"
            f"Volume: {row['TOTAL_VOLUME']:,}<br>"
            "<extra></extra>"
        )
    ))

# Quadrant reference lines
fig.add_hline(y=median_neg, line_dash="dot", line_color="#64748b", opacity=0.5)
fig.add_vline(x=median_aht, line_dash="dot", line_color="#64748b", opacity=0.5)

# Quadrant labels
fig.add_annotation(x=max_aht, y=max_neg, text="⚠️ ACT NOW",
                   showarrow=False, font=dict(color='#EF4444', size=11))
fig.add_annotation(x=min_aht, y=min_neg, text="✅ HEALTHY",
                   showarrow=False, font=dict(color='#10B981', size=11))
```

---

#### 4.1.6 Resolution Flow — Sankey Diagram

**Chart Type:** `go.Sankey`

**Purpose:** Visualize how calls flow from category through resolution steps to final outcome. Reveals which paths lead to resolution vs. failure.

| Attribute | Mapping |
|---|---|
| Source Nodes (Left) | `AI_CATEGORY` |
| Target Nodes (Right) | `AI_OUTCOME` (Resolved, Unresolved, Callback, Escalated) |
| Link Value | `COUNT(*)` — number of calls on each path |
| Link Color | Outcome-coded (green=Resolved, red=Unresolved, amber=Callback, purple=Escalated) |
| Node Color | Category palette (left), Outcome palette (right) |

```python
# Build node and link lists from grouped data
categories = df['AI_CATEGORY'].unique().tolist()
outcomes = ['Resolved', 'Unresolved', 'Callback', 'Escalated']
all_nodes = categories + outcomes

outcome_colors = {
    'Resolved':   'rgba(16,185,129,0.5)',
    'Unresolved': 'rgba(239,68,68,0.5)',
    'Callback':   'rgba(245,158,11,0.5)',
    'Escalated':  'rgba(139,92,246,0.5)'
}

source_indices, target_indices, values, link_colors = [], [], [], []
for _, row in flow_df.iterrows():
    source_indices.append(all_nodes.index(row['AI_CATEGORY']))
    target_indices.append(all_nodes.index(row['AI_OUTCOME']))
    values.append(row['CALL_COUNT'])
    link_colors.append(outcome_colors[row['AI_OUTCOME']])

fig = go.Figure(go.Sankey(
    node=dict(
        pad=20, thickness=25, line=dict(color='#1e293b', width=1),
        label=all_nodes,
        color=[category_colors.get(n, '#64748b') for n in all_nodes]
    ),
    link=dict(
        source=source_indices,
        target=target_indices,
        value=values,
        color=link_colors
    )
))
```

**SQL:**

```sql
SELECT
    AI_CATEGORY,
    AI_OUTCOME,
    COUNT(*) AS CALL_COUNT
FROM FACT_CALLS
WHERE CALL_START_TS >= :start_ts AND CALL_START_TS <= :end_ts
GROUP BY 1, 2
ORDER BY 1, 2;
```

---

### 4.2 TAB 2 — Category Deep Dive

**Purpose:** Deep analysis of each call category's sentiment profile, outcome distribution, and volume trends. Answer: "Which categories have the worst outcomes and why?"

---

#### 4.2.1 Sentiment Diverging Bar Chart

**Chart Type:** `go.Bar` — Horizontal diverging (negative left, positive right)

**Purpose:** Instantly compare which categories have the best/worst sentiment profiles.

| Attribute | Mapping |
|---|---|
| Y-Axis | `AI_CATEGORY` (categorical) |
| X-Axis (Left/Negative) | `-1 × NEGATIVE_SENTIMENT_PCT` |
| X-Axis (Right/Positive) | `POSITIVE_SENTIMENT_PCT` |
| Neutral | `NEUTRAL_SENTIMENT_PCT` (can be omitted or shown as gap) |
| Negative Color | `rgba(239, 68, 68, 0.7)` |
| Positive Color | `rgba(16, 185, 129, 0.7)` |
| Sort | By net sentiment (positive − negative) descending |

```python
fig = go.Figure()

fig.add_trace(go.Bar(
    y=df['AI_CATEGORY'],
    x=-df['NEGATIVE_PCT'],
    orientation='h',
    name='Negative',
    marker_color='rgba(239,68,68,0.7)',
    text=df['NEGATIVE_PCT'].apply(lambda x: f'{x:.0f}%'),
    textposition='inside',
    hovertemplate='%{y}: %{text} Negative<extra></extra>'
))

fig.add_trace(go.Bar(
    y=df['AI_CATEGORY'],
    x=df['POSITIVE_PCT'],
    orientation='h',
    name='Positive',
    marker_color='rgba(16,185,129,0.7)',
    text=df['POSITIVE_PCT'].apply(lambda x: f'{x:.0f}%'),
    textposition='inside',
    hovertemplate='%{y}: %{text} Positive<extra></extra>'
))

fig.update_layout(
    barmode='overlay',
    xaxis=dict(
        zeroline=True, zerolinewidth=2, zerolinecolor='#334155',
        title='← Negative     |     Positive →',
        tickvals=[-60,-40,-20,0,20,40,60,80],
        ticktext=['60%','40%','20%','0','20%','40%','60%','80%']
    ),
    yaxis=dict(categoryorder='total ascending')
)
```

**SQL:**

```sql
SELECT
    AI_CATEGORY,
    AVG(NEGATIVE_SENTIMENT_PCT)  AS NEGATIVE_PCT,
    AVG(POSITIVE_SENTIMENT_PCT)  AS POSITIVE_PCT,
    100 - AVG(NEGATIVE_SENTIMENT_PCT) - AVG(POSITIVE_SENTIMENT_PCT) AS NEUTRAL_PCT
FROM AGG_DAILY_METRICS
WHERE CALL_DATE >= :start_date AND CALL_DATE <= :end_date
GROUP BY 1;
```

---

#### 4.2.2 Outcome × Category Heatmap

**Chart Type:** `go.Heatmap` (annotated)

**Purpose:** Show which categories have the highest rates of each outcome type. Hot spots reveal problem areas.

| Attribute | Mapping |
|---|---|
| X-Axis | `AI_OUTCOME` (Resolved, Unresolved, Callback, Escalated) |
| Y-Axis | `AI_CATEGORY` |
| Z-Value (Color) | Percentage of calls in that category with that outcome |
| Color Scale | `Greens` for Resolved column, `Reds` for Unresolved, or unified `RdYlGn` |
| Annotations | Percentage value in each cell |
| Hover | Category, Outcome, Percentage, Absolute count |

```python
fig = go.Figure(go.Heatmap(
    z=pivot_df.values,
    x=outcome_columns,
    y=category_labels,
    colorscale='RdYlGn',
    text=pivot_df.values,
    texttemplate='%{text:.0f}%',
    textfont=dict(size=13, color='white'),
    hovertemplate=(
        'Category: %{y}<br>'
        'Outcome: %{x}<br>'
        'Rate: %{z:.1f}%<br>'
        '<extra></extra>'
    ),
    colorbar=dict(title='%', ticksuffix='%')
))

fig.update_layout(
    yaxis=dict(categoryorder='category ascending'),
    xaxis=dict(side='top')
)
```

**SQL:**

```sql
SELECT
    AI_CATEGORY,
    AI_OUTCOME,
    COUNT(*) AS CNT,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY AI_CATEGORY) AS OUTCOME_PCT
FROM FACT_CALLS
WHERE CALL_START_TS >= :start_ts AND CALL_START_TS <= :end_ts
GROUP BY 1, 2;
```

Then pivot in Pandas:

```python
pivot_df = df.pivot(index='AI_CATEGORY', columns='AI_OUTCOME', values='OUTCOME_PCT').fillna(0)
pivot_df = pivot_df[['Resolved', 'Callback', 'Escalated', 'Unresolved']]
```

---

#### 4.2.3 Category Volume Stacked Area

**Chart Type:** `go.Scatter` with `stackgroup`

**Purpose:** Show how the category mix shifts over time. Expanding categories indicate emerging trends.

| Attribute | Mapping |
|---|---|
| X-Axis | `CALL_WEEK` |
| Y-Axis | `SUM(CALL_COUNT)` per category (stacked) |
| Stack Group | `'one'` (forces stacking) |
| Colors | Category-specific palette |
| Fill | `tonexty` for stacking |
| Hover | Week, Category, Volume, % of week total |

```python
for category in categories:
    cat_df = df[df['AI_CATEGORY'] == category]
    fig.add_trace(go.Scatter(
        x=cat_df['CALL_WEEK'],
        y=cat_df['WEEKLY_VOLUME'],
        name=category,
        mode='lines',
        stackgroup='one',
        line=dict(width=0.5, color=category_colors[category]),
        fillcolor=category_colors_transparent[category],
        hovertemplate=(
            f'<b>{category}</b><br>'
            'Week: %{x}<br>'
            'Volume: %{y:,}<br>'
            '<extra></extra>'
        )
    ))
```

**SQL:**

```sql
SELECT
    DATE_TRUNC('week', CALL_DATE) AS CALL_WEEK,
    AI_CATEGORY,
    SUM(CALL_COUNT) AS WEEKLY_VOLUME
FROM AGG_DAILY_METRICS
WHERE CALL_DATE >= :start_date AND CALL_DATE <= :end_date
GROUP BY 1, 2
ORDER BY 1, 2;
```

---

### 4.3 TAB 3 — Team Performance

**Purpose:** Compare teams across multiple performance dimensions per category. Answer: "Which teams handle which categories best, and who needs coaching?"

---

#### 4.3.1 AHT by Category × Team — Dot Plot (Cleveland)

**Chart Type:** `go.Scatter` — Horizontal dot/dumbbell plot

**Purpose:** Compare handle times across teams for each category without bar chart clutter. Dot spread shows team variance.

| Attribute | Mapping |
|---|---|
| Y-Axis | `AI_CATEGORY` (categorical) |
| X-Axis | `AVG(HANDLE_TIME_SEC) / 60` — minutes |
| Points | One dot per team, color-coded |
| Connecting Line | Horizontal line connecting min to max team AHT per category (dumbbell) |
| Point Size | 12px |
| Hover | Team name, Category, AHT in mm:ss format |
| Reference Line | Vertical dashed line at overall median AHT |

```python
team_colors = {
    'Alpha': '#3B82F6', 'Beta': '#8B5CF6',
    'Gamma': '#06B6D4', 'Delta': '#10B981'
}

# Dumbbell connecting lines
for category in categories:
    cat_data = df[df['AI_CATEGORY'] == category]
    fig.add_trace(go.Scatter(
        x=[cat_data['AHT_MIN'].min(), cat_data['AHT_MIN'].max()],
        y=[category, category],
        mode='lines',
        line=dict(color='#334155', width=2),
        showlegend=False,
        hoverinfo='skip'
    ))

# Team dots
for team in teams:
    team_data = df[df['TEAM_NAME'] == team]
    fig.add_trace(go.Scatter(
        x=team_data['AHT_MIN'],
        y=team_data['AI_CATEGORY'],
        mode='markers',
        name=team,
        marker=dict(size=12, color=team_colors[team],
                    line=dict(width=2, color='white')),
        hovertemplate=(
            f'<b>{team}</b><br>'
            'Category: %{y}<br>'
            'AHT: %{x:.1f} min<br>'
            '<extra></extra>'
        )
    ))

fig.add_vline(x=overall_median_aht, line_dash="dash",
              line_color="#64748b", opacity=0.5,
              annotation_text=f"Median: {overall_median_aht:.1f}m")
```

**SQL:**

```sql
SELECT
    TEAM_NAME,
    AI_CATEGORY,
    AVG(AVG_HANDLE_TIME_SEC) / 60.0 AS AHT_MIN
FROM AGG_DAILY_METRICS
WHERE CALL_DATE >= :start_date AND CALL_DATE <= :end_date
GROUP BY 1, 2;
```

---

#### 4.3.2 Team Resolution Rate — Horizontal Bar

**Chart Type:** `go.Bar` — Horizontal

| Attribute | Mapping |
|---|---|
| Y-Axis | `TEAM_NAME` |
| X-Axis | `AVG(RESOLUTION_RATE)` (%) |
| Bar Color | Team-specific color |
| Text | Resolution rate value inside bar |
| Reference | Vertical line at target (e.g., 80%) |
| Sort | Descending by resolution rate |

```python
fig = go.Figure(go.Bar(
    y=df['TEAM_NAME'],
    x=df['RESOLUTION_RATE'],
    orientation='h',
    marker_color=[team_colors[t] for t in df['TEAM_NAME']],
    text=df['RESOLUTION_RATE'].apply(lambda x: f'{x:.1f}%'),
    textposition='inside',
    textfont=dict(color='white', size=13, family='Space Mono')
))
fig.add_vline(x=80, line_dash="dash", line_color="#10B981", opacity=0.5,
              annotation_text="Target: 80%")
```

---

#### 4.3.3 Team Sentiment — Horizontal Bar

Same structure as 4.3.2, using `AVG(AVG_SENTIMENT)` on X-axis (0.0–1.0 scale).

---

#### 4.3.4 Multi-Metric Team Heatmap

**Chart Type:** `go.Heatmap` (annotated)

**Purpose:** Single view comparing all teams across all key metrics. Conditional coloring highlights best/worst performers.

| Attribute | Mapping |
|---|---|
| Y-Axis | `TEAM_NAME` |
| X-Axis | Metrics: AHT (min), Resolution %, Sentiment, Callback % |
| Z-Value | Normalized score (0–1) per metric. For AHT and Callback: inverted (lower=better=green). For Resolution and Sentiment: direct (higher=better=green) |
| Annotations | Raw values in each cell |
| Color Scale | `RdYlGn` |

**Normalization logic:**

```python
def normalize(series, invert=False):
    min_val, max_val = series.min(), series.max()
    norm = (series - min_val) / (max_val - min_val + 1e-9)
    return 1 - norm if invert else norm

df['AHT_NORM']        = normalize(df['AHT_MIN'], invert=True)
df['RESOLUTION_NORM']  = normalize(df['RESOLUTION_RATE'])
df['SENTIMENT_NORM']   = normalize(df['AVG_SENTIMENT'])
df['CALLBACK_NORM']    = normalize(df['CALLBACK_RATE'], invert=True)
```

**SQL:**

```sql
SELECT
    TEAM_NAME,
    AVG(AVG_HANDLE_TIME_SEC) / 60.0  AS AHT_MIN,
    AVG(RESOLUTION_RATE)              AS RESOLUTION_RATE,
    AVG(AVG_SENTIMENT)                AS AVG_SENTIMENT,
    AVG(CALLBACK_RATE)                AS CALLBACK_RATE
FROM AGG_DAILY_METRICS
WHERE CALL_DATE >= :start_date AND CALL_DATE <= :end_date
GROUP BY 1;
```

---

### 4.4 TAB 4 — Call Explorer

**Purpose:** Drill into individual call records with all AI-enriched fields. Answer: "Show me the actual calls — what happened, what did AI find, what was the outcome?"

---

#### 4.4.1 Interactive Call Table

**Component:** `dash_table.DataTable` with sorting, filtering, pagination, and conditional styling

**Table Columns:**

| Column Header | Source Field | Width | Format/Style |
|---|---|---|---|
| Call ID | `CALL_ID` | 120px | Monospace, cyan color, clickable to expand |
| Start Time | `CALL_START_TS` | 140px | `YYYY-MM-DD HH:MM` |
| Duration | `HANDLE_TIME_SEC` | 80px | Formatted as `mm:ss` |
| Category | `AI_CATEGORY` | 120px | Colored badge |
| Queue | `QUEUE_NAME` | 100px | Plain text |
| Division | `DIVISION_NAME` | 90px | Plain text |
| Sentiment | `AI_SENTIMENT_LABEL` | 100px | Colored dot + label (Green=Positive, Amber=Neutral, Red=Negative) |
| Score | `AI_SENTIMENT_SCORE` | 70px | `0.00–1.00` with background gradient |
| Outcome | `AI_OUTCOME` | 100px | Colored badge (Green=Resolved, Red=Unresolved, Amber=Callback, Purple=Escalated) |
| Repeat? | `IS_REPEAT_CALLER` | 70px | ⚠️ icon if true |
| AI Summary | `AI_SUMMARY` | 300px | Truncated to 120 chars, expand on click |
| Resolution Steps | `AI_RESOLUTION_STEPS` | 250px | Pipe-separated steps, formatted as flow |

**DataTable Configuration:**

```python
dash_table.DataTable(
    id='call-explorer-table',
    columns=[
        {'name': 'Call ID', 'id': 'CALL_ID', 'type': 'text'},
        {'name': 'Start Time', 'id': 'CALL_START_TS', 'type': 'datetime'},
        {'name': 'Duration', 'id': 'DURATION_FMT', 'type': 'text'},
        {'name': 'Category', 'id': 'AI_CATEGORY', 'type': 'text'},
        {'name': 'Queue', 'id': 'QUEUE_NAME', 'type': 'text'},
        {'name': 'Division', 'id': 'DIVISION_NAME', 'type': 'text'},
        {'name': 'Sentiment', 'id': 'AI_SENTIMENT_LABEL', 'type': 'text'},
        {'name': 'Score', 'id': 'AI_SENTIMENT_SCORE', 'type': 'numeric',
         'format': Format(precision=2)},
        {'name': 'Outcome', 'id': 'AI_OUTCOME', 'type': 'text'},
        {'name': 'Repeat?', 'id': 'IS_REPEAT_CALLER', 'type': 'text'},
        {'name': 'AI Summary', 'id': 'AI_SUMMARY', 'type': 'text'},
        {'name': 'Resolution Steps', 'id': 'AI_RESOLUTION_STEPS', 'type': 'text'},
    ],
    page_size=25,
    page_action='native',
    sort_action='native',
    sort_mode='multi',
    filter_action='native',
    style_table={'overflowX': 'auto'},
    style_header={
        'backgroundColor': '#111827',
        'color': '#94A3B8',
        'fontWeight': '600',
        'fontSize': '11px',
        'textTransform': 'uppercase',
        'letterSpacing': '0.5px',
        'border': '1px solid #1E293B'
    },
    style_cell={
        'backgroundColor': '#111827',
        'color': '#CBD5E1',
        'border': '1px solid #1E293B',
        'fontSize': '13px',
        'padding': '10px 12px',
        'fontFamily': 'DM Sans, sans-serif',
        'whiteSpace': 'normal',
        'maxWidth': '300px',
        'textOverflow': 'ellipsis'
    },
    style_data_conditional=[
        # Sentiment coloring
        {'if': {'filter_query': '{AI_SENTIMENT_LABEL} = "Positive"',
                'column_id': 'AI_SENTIMENT_LABEL'},
         'color': '#10B981', 'fontWeight': '600'},
        {'if': {'filter_query': '{AI_SENTIMENT_LABEL} = "Negative"',
                'column_id': 'AI_SENTIMENT_LABEL'},
         'color': '#EF4444', 'fontWeight': '600'},
        {'if': {'filter_query': '{AI_SENTIMENT_LABEL} = "Neutral"',
                'column_id': 'AI_SENTIMENT_LABEL'},
         'color': '#F59E0B', 'fontWeight': '600'},
        # Outcome coloring
        {'if': {'filter_query': '{AI_OUTCOME} = "Resolved"',
                'column_id': 'AI_OUTCOME'},
         'color': '#10B981', 'fontWeight': '600'},
        {'if': {'filter_query': '{AI_OUTCOME} = "Unresolved"',
                'column_id': 'AI_OUTCOME'},
         'color': '#EF4444', 'fontWeight': '600'},
        {'if': {'filter_query': '{AI_OUTCOME} = "Callback"',
                'column_id': 'AI_OUTCOME'},
         'color': '#F59E0B', 'fontWeight': '600'},
        {'if': {'filter_query': '{AI_OUTCOME} = "Escalated"',
                'column_id': 'AI_OUTCOME'},
         'color': '#8B5CF6', 'fontWeight': '600'},
        # Repeat caller highlight
        {'if': {'filter_query': '{IS_REPEAT_CALLER} = "⚠️"'},
         'backgroundColor': 'rgba(239,68,68,0.08)'},
    ],
    tooltip_data=[
        {col: {'value': str(row[col]), 'type': 'markdown'}
         for col in ['AI_SUMMARY', 'AI_RESOLUTION_STEPS']}
        for row in df.to_dict('records')
    ],
    tooltip_duration=None
)
```

**SQL:**

```sql
SELECT
    CALL_ID,
    CALL_START_TS,
    HANDLE_TIME_SEC,
    QUEUE_NAME,
    DIVISION_NAME,
    TEAM_NAME,
    AI_CATEGORY,
    AI_SENTIMENT_LABEL,
    AI_SENTIMENT_SCORE,
    AI_OUTCOME,
    AI_RESOLUTION_STEPS,
    AI_SUMMARY,
    IS_REPEAT_CALLER
FROM FACT_CALLS
WHERE CALL_START_TS >= :start_ts AND CALL_START_TS <= :end_ts
ORDER BY CALL_START_TS DESC
LIMIT 500;
```

---

## 5. Color Palette & Design Tokens

### 5.1 Category Colors

| Category | Hex | RGBA (70% opacity) |
|---|---|---|
| Billing | `#3B82F6` | `rgba(59,130,246,0.7)` |
| Tech Support | `#8B5CF6` | `rgba(139,92,246,0.7)` |
| Account Access | `#06B6D4` | `rgba(6,182,212,0.7)` |
| Service Outage | `#EF4444` | `rgba(239,68,68,0.7)` |
| New Service | `#10B981` | `rgba(16,185,129,0.7)` |
| Complaints | `#F59E0B` | `rgba(245,158,11,0.7)` |

### 5.2 Team Colors

| Team | Hex |
|---|---|
| Alpha | `#3B82F6` |
| Beta | `#8B5CF6` |
| Gamma | `#06B6D4` |
| Delta | `#10B981` |

### 5.3 Outcome Colors

| Outcome | Hex | Usage |
|---|---|---|
| Resolved | `#10B981` | Badges, Sankey links, heatmap |
| Unresolved | `#EF4444` | Badges, Sankey links, heatmap |
| Callback | `#F59E0B` | Badges, Sankey links, heatmap |
| Escalated | `#8B5CF6` | Badges, Sankey links, heatmap |

### 5.4 Sentiment Colors

| Sentiment | Hex |
|---|---|
| Positive | `#10B981` |
| Neutral | `#F59E0B` |
| Negative | `#EF4444` |

### 5.5 Background / UI Tokens

| Token | Hex | Usage |
|---|---|---|
| `bg-primary` | `#0A0E1A` | Page background |
| `bg-card` | `#111827` | Card backgrounds |
| `border` | `#1E293B` | Card borders, grid lines |
| `text-primary` | `#F1F5F9` | Headings, values |
| `text-secondary` | `#94A3B8` | Labels, descriptions |
| `text-muted` | `#64748B` | Subtle text, axis ticks |

### 5.6 Plotly Layout Template

Apply to every chart for consistency:

```python
CHART_TEMPLATE = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(family='DM Sans', color='#94A3B8', size=12),
    title_font=dict(family='DM Sans', color='#F1F5F9', size=14),
    xaxis=dict(
        gridcolor='rgba(30,41,59,0.5)',
        linecolor='#1E293B',
        tickfont=dict(color='#64748B', size=10),
        zeroline=False
    ),
    yaxis=dict(
        gridcolor='rgba(30,41,59,0.5)',
        linecolor='#1E293B',
        tickfont=dict(color='#64748B', size=10),
        zeroline=False
    ),
    legend=dict(
        font=dict(color='#94A3B8', size=11),
        bgcolor='rgba(0,0,0,0)',
        bordercolor='rgba(0,0,0,0)'
    ),
    margin=dict(l=60, r=20, t=40, b=40),
    hoverlabel=dict(
        bgcolor='#1E293B',
        font_size=12,
        font_family='DM Sans',
        font_color='#F1F5F9',
        bordercolor='#334155'
    )
)
```

---

## 6. Callback Architecture

### 6.1 State Management

```python
# Shared state store — holds current filter values
dcc.Store(id='filter-state', data={
    'period': '7D',
    'start_date': None,     # Computed from period
    'end_date': None,        # Computed from period
    'divisions': [],         # Empty = all
    'queues': [],            # Empty = all
    'categories': [],        # Empty = all
    'teams': []              # Empty = all
})
```

### 6.2 Callback Chain

```
[Period Buttons / Division Dropdown / Queue Dropdown / Category Dropdown / Team Dropdown]
    │
    ▼
filter-state (dcc.Store) ── updates on any filter change
    │
    ├──▶ KPI Cards (5x)
    ├──▶ Volume+Sentiment Chart
    ├──▶ Resolution Trend Chart
    ├──▶ Treemap
    ├──▶ Priority Scatter
    ├──▶ Sankey Flow
    ├──▶ Diverging Bars
    ├──▶ Outcome Heatmap
    ├──▶ Stacked Area
    ├──▶ Dot Plot
    ├──▶ Team Bars (2x)
    ├──▶ Team Heatmap
    └──▶ Call Explorer Table
```

### 6.3 Cross-Chart Drill-Down

| Source Interaction | Target Action |
|---|---|
| Click treemap cell | Filter Category dropdown → update all charts |
| Click scatter bubble | Filter to that category → switch to Category tab |
| Click Sankey node | Filter to that category or outcome |
| Click heatmap cell | Filter Category + Outcome → switch to Call Explorer tab |
| Click team heatmap cell | Filter Team + Metric → highlight in other charts |

### 6.4 Sample Callback

```python
@app.callback(
    [Output('volume-sentiment-chart', 'figure'),
     Output('resolution-trend-chart', 'figure'),
     Output('treemap-chart', 'figure'),
     Output('scatter-chart', 'figure'),
     Output('sankey-chart', 'figure')],
    [Input('filter-state', 'data')]
)
def update_overview_charts(filters):
    start_date, end_date = compute_date_range(filters['period'])
    
    # Query Snowflake with filters
    weekly_df = query_weekly_metrics(
        start_date, end_date,
        filters['divisions'], filters['queues'],
        filters['categories'], filters['teams']
    )
    
    vol_sent_fig = build_volume_sentiment_chart(weekly_df)
    res_trend_fig = build_resolution_trend_chart(weekly_df)
    treemap_fig = build_treemap(category_df)
    scatter_fig = build_priority_scatter(category_team_df)
    sankey_fig = build_sankey(flow_df)
    
    return vol_sent_fig, res_trend_fig, treemap_fig, scatter_fig, sankey_fig
```

---

## 7. Advanced Analytics (Phase 2 Enhancements)

### 7.1 Sentiment Trajectory Analysis

Track how sentiment changes within a call (start vs. end) to measure agent effectiveness.

**Chart Type:** `go.Scatter` — Arrow/slope chart

| Attribute | Mapping |
|---|---|
| Y-Axis | `AI_SENTIMENT_START` → `AI_SENTIMENT_END` (connected) |
| X-Axis | Categories or teams |
| Color | Green if sentiment improved, Red if worsened |

**SQL:**

```sql
SELECT
    AI_CATEGORY,
    TEAM_NAME,
    AVG(AI_SENTIMENT_START)  AS AVG_SENT_START,
    AVG(AI_SENTIMENT_END)    AS AVG_SENT_END,
    AVG(AI_SENTIMENT_END) - AVG(AI_SENTIMENT_START) AS SENT_DELTA
FROM FACT_CALLS
WHERE CALL_START_TS >= :start_ts AND CALL_START_TS <= :end_ts
GROUP BY 1, 2;
```

### 7.2 Repeat Caller Analysis

**Chart Type:** `go.Bar` — Grouped bar showing repeat vs. first-time callers per category

**SQL:**

```sql
SELECT
    AI_CATEGORY,
    IS_REPEAT_CALLER,
    COUNT(*) AS CALL_COUNT,
    AVG(HANDLE_TIME_SEC)/60.0 AS AVG_AHT_MIN,
    AVG(AI_SENTIMENT_SCORE) AS AVG_SENTIMENT
FROM FACT_CALLS
WHERE CALL_START_TS >= :start_ts
GROUP BY 1, 2;
```

### 7.3 Resolution Step Effectiveness

Correlate specific AI-identified resolution steps with outcomes.

**Chart Type:** `go.Heatmap` — Resolution step × Outcome rate

**SQL:**

```sql
-- Flatten resolution steps
SELECT
    f.value::STRING           AS RESOLUTION_STEP,
    c.AI_OUTCOME,
    COUNT(*)                  AS CNT
FROM FACT_CALLS c,
LATERAL FLATTEN(input => SPLIT(c.AI_RESOLUTION_STEPS, '|')) f
WHERE c.CALL_START_TS >= :start_ts
GROUP BY 1, 2;
```

### 7.4 Queue Wait Time vs. Sentiment Correlation

**Chart Type:** `go.Scatter` — Scatter with trendline

Shows if longer wait times correlate with worse sentiment. Useful for staffing decisions.

### 7.5 Hourly Volume Heatmap

**Chart Type:** `go.Heatmap` — Day of week × Hour of day

Helps optimize staffing schedules.

**SQL:**

```sql
SELECT
    DAYNAME(CALL_START_TS)            AS DAY_OF_WEEK,
    HOUR(CALL_START_TS)               AS HOUR_OF_DAY,
    COUNT(*)                          AS CALL_COUNT
FROM FACT_CALLS
WHERE CALL_START_TS >= :start_ts
GROUP BY 1, 2;
```

---

## 8. Configuration & Environment

### 8.1 requirements.txt

```
dash==2.17.1
dash-bootstrap-components==1.6.0
plotly==5.22.0
pandas==2.2.2
snowflake-connector-python==3.10.0
snowflake-sqlalchemy==1.5.3
flask-caching==2.1.0
gunicorn==22.0.0
python-dotenv==1.0.1
```

### 8.2 Snowflake Connection Config

```python
# config.py
import os
from dotenv import load_dotenv
load_dotenv()

SNOWFLAKE_CONFIG = {
    'account':   os.getenv('SNOWFLAKE_ACCOUNT'),     # e.g., HUBBXYZ-XA96647
    'user':      os.getenv('SNOWFLAKE_USER'),
    'password':  os.getenv('SNOWFLAKE_PASSWORD'),
    'warehouse': os.getenv('SNOWFLAKE_WAREHOUSE'),
    'database':  os.getenv('SNOWFLAKE_DATABASE'),
    'schema':    os.getenv('SNOWFLAKE_SCHEMA'),
    'role':      os.getenv('SNOWFLAKE_ROLE')
}

CACHE_CONFIG = {
    'CACHE_TYPE': 'filesystem',
    'CACHE_DIR': '/tmp/dash_cache',
    'CACHE_DEFAULT_TIMEOUT': 300   # 5 minutes
}
```

### 8.3 .env Template

```env
SNOWFLAKE_ACCOUNT=HUBBXYZ-XA96647
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=your_password
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=ANALYTICS_DB
SNOWFLAKE_SCHEMA=CONTACT_CENTER
SNOWFLAKE_ROLE=ANALYST_ROLE
```

---

## 9. Chart Summary Reference

Quick lookup table for every visualization in the dashboard:

| # | Tab | Chart Name | Plotly Type | X-Axis | Y-Axis | Color/Size | Key Insight |
|---|---|---|---|---|---|---|---|
| 1 | Overview | Volume+Sentiment | `go.Bar` + `go.Scatter` | Week | Volume / Sentiment | Blue bars, Amber line | Stress period correlation |
| 2 | Overview | Resolution Trend | `go.Scatter` (2 lines) | Week | Rate % | Green / Red | Ops improvement over time |
| 3 | Overview | Category Treemap | `px.treemap` | — | — | Sentiment (RdYlGn) / Area=Volume | Volume distribution at a glance |
| 4 | Overview | Priority Scatter | `go.Scatter` (bubble) | AHT (min) | Neg Sentiment % | Bubble size=Volume | Where to focus resources |
| 5 | Overview | Resolution Flow | `go.Sankey` | Category→Outcome | — | Outcome color | Path effectiveness |
| 6 | Category | Diverging Bars | `go.Bar` (horizontal) | Sentiment % | Category | Red(neg) / Green(pos) | Category sentiment profile |
| 7 | Category | Outcome Heatmap | `go.Heatmap` | Outcome | Category | RdYlGn intensity | Hot-spot problem detection |
| 8 | Category | Stacked Area | `go.Scatter` (stacked) | Week | Volume | Category colors | Mix shift over time |
| 9 | Teams | AHT Dot Plot | `go.Scatter` (dumbbell) | AHT (min) | Category | Team color dots | Cross-team AHT comparison |
| 10 | Teams | Resolution Bars | `go.Bar` (horizontal) | Resolution % | Team | Team colors | Team effectiveness ranking |
| 11 | Teams | Sentiment Bars | `go.Bar` (horizontal) | Sentiment | Team | Team colors | Team customer experience |
| 12 | Teams | Multi-Metric Heatmap | `go.Heatmap` | Metrics | Team | Normalized RdYlGn | Holistic team comparison |
| 13 | Calls | Call Explorer | `dash_table.DataTable` | — | — | Conditional cell coloring | Individual call drill-down |

---

## 10. Development Phases

| Phase | Scope | Duration |
|---|---|---|
| Phase 1 | Data model, Snowflake views, Plotly template, Tab 1 (Overview) | Week 1–2 |
| Phase 2 | Tab 2 (Categories) + Tab 3 (Teams) with all charts | Week 3 |
| Phase 3 | Tab 4 (Call Explorer) + cross-chart drill-down callbacks | Week 4 |
| Phase 4 | Caching, performance optimization, Docker deployment | Week 5 |
| Phase 5 | Advanced analytics (Section 7), sentiment trajectory, repeat caller analysis | Week 6+ |
