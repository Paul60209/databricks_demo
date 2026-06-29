# FPT-FAI AI チャットボット — Databricks デモ

Databricks を基盤としたエンド・ツー・エンドの AI システムです。  
Chainlit のチャット UI から自然言語で質問すると、LangGraph マルチエージェントが処理し、MCP Server 経由で Databricks に問い合わせ、構造化された回答とダウンロード可能なデータファイルを返します。

![アーキテクチャ図](<FPT_databricks+agentic AI_architecture.png>)

---

## 目次

1. [セマンティックレイヤー](#セマンティックレイヤー)
2. [MCP サーバー](#mcp-サーバー)
3. [マルチ AI エージェント](#マルチ-ai-エージェント)
4. [フロントエンド](#フロントエンド)
5. [LangSmith トレーシング](#langsmith-トレーシング)

---

## セマンティックレイヤー

**場所：** `sql_dlt.sql` / `pyspark_dlt.py` · `semantic_model.yml`

**Delta Live Tables (DLT)** で構築し、**Unity Catalog** が管理する 4 層の Lakehouse データパイプラインです。

```
生データ CSV
  └─► Bronze   (demo.bronze)     — 外部テーブル（Databricks UI から取り込み）
        └─► Silver  (demo.silver)    — DLT：クレンジング・重複排除・バリデーション
              └─► Gold    (demo.golden)   — DLT：月次集計
                    └─► Diamond (demo.diamond)  — AI 向けセマンティックテーブル
```

| レイヤー | テーブル | 役割 |
|----------|----------|------|
| Silver | `dim_customers` | 国名の標準化・メール検証・重複排除 |
| Silver | `fct_orders` | 日付形式の統一・無効金額の除去 |
| Silver | `fct_orders_extended` | 注文テーブルと顧客テーブルのストリーム-スタティック Join |
| Gold | `agg_customer_monthly_stats` | 顧客ごとの月次注文数・売上集計 |
| Diamond | `sem_customer_transaction_summary` | 顧客ごとの月次統計（AOV・注文数・金額） |
| Diamond | `sem_regional_monthly_aov` | 国別・月別の平均注文金額（AOV） |

`semantic_model.yml` は Diamond レイヤー上にビジネス向けのメトリクスおよびディメンション定義を登録し、**Databricks AI/BI Genie** による自然言語クエリを可能にします。

---

## MCP サーバー

**場所：** `mcp_server/mcp_server.py` · `databricks_query.py`

**FastMCP**（stdio トランスポート）で実装された MCP サーバーで、3 つのツールを MCP 互換クライアントに公開します。  
`databricks_query.py` が Databricks SQL コネクターの基盤関数を提供します。

### ツール一覧

| ツール | 説明 | 主なパラメータ |
|--------|------|----------------|
| `get_customer_transaction_summary` | Diamond レイヤーから顧客ごとの月次統計を取得 | `customer_ids`・`customer_names`・`months` |
| `get_regional_monthly_aov` | Diamond レイヤーから地域・月別の AOV を取得 | `countries`・`months` |
| `query_data_with_natural_language` | Claude Haiku で自然言語を SQL に変換し Databricks で実行 | `question`（自由記述） |

### 呼び出しチェーン

```
MCP クライアント
  └─► mcp_server.py  (FastMCP, stdio)
        ├─► get_customer_transaction_summary
        │     └─► databricks_query._query_customer()  →  Databricks SQL Warehouse
        ├─► get_regional_monthly_aov
        │     └─► databricks_query._query_aov()       →  Databricks SQL Warehouse
        └─► query_data_with_natural_language
              ├─► _generate_sql()   →  Claude Haiku（自然言語 → SQL）
              ├─► _validate_sql()   （DDL・複数ステートメントをブロック）
              └─► _run_query()      →  Databricks SQL Warehouse
```

---

## マルチ AI エージェント

**場所：** `agent/`

**LangGraph** `StateGraph` で実装された 2 つのエージェントが PASS / FAIL フィードバックループを形成します（最大 3 回のイテレーション）。

### エージェント一覧

| エージェント | モデル | 役割 |
|-------------|--------|------|
| Think Agent（`think_agent.py`） | claude-sonnet-4-6 | MCP ツールを呼び出してデータを取得し、ビジネス回答を生成 |
| Judge Agent（`judge_agent.py`） | claude-haiku-4-5-20251001 | 回答の品質を評価し、PASS または FAIL とフィードバックを返す |

### 状態（`state.py`）

`AgentState` には `messages`・`user_question`・`tool_results`・`think_answer`・`judge_feedback`・`iteration_count`・`final_answer`・`is_complete` が含まれます。

### 呼び出しチェーン

```
run_agent.py  /  chainlit_app.py
  └─► agent/mcp_client.py   make_mcp_client()   （MultiServerMCPClient、stdio サブプロセス）
        └─► agent/graph.py  build_graph(tools)   （StateGraph）
              ├─► think ノード（create_think_node）
              │     ├─► Claude Sonnet  bind_tools(mcp_tools)
              │     └─► tool.ainvoke()  →  MCP Server  →  Databricks
              └─► judge ノード（judge_node）
                    ├─► Claude Haiku  → JSON {"verdict": "PASS"|"FAIL", "feedback": "..."} を返す
                    └─► route_after_judge()
                          ├─► PASS  →  END（final_answer を設定）
                          ├─► FAIL  →  think（フィードバックを注入して再試行）
                          └─► イテレーション >= 3  →  END（強制終了）
```

---

## フロントエンド

**場所：** `front_end/`

多言語対応とファイル入出力を備えた **Chainlit** チャット UI です。

### 主な機能

| 機能 | 詳細 |
|------|------|
| **多言語** | 入力言語を自動検出：繁体字中国語 / 英語 / 日本語 |
| **ファイルアップロード** | CSV・Excel・PDF・Word に対応 — 内容を解析してエージェントのコンテキストに注入 |
| **ファイルダウンロード** | ツール呼び出しごとにクエリ結果を CSV と Excel で自動エクスポート |
| **インタラクティブチャート** | Plotly グラフ（キーワードトリガー：*chart / 圖表 / グラフ*） |
| **PDF レポート** | キーワードトリガー（*report / 報告 / レポート*）で質問・回答・データ表を含む PDF を生成 |

### 主なモジュール

| ファイル | 役割 |
|----------|------|
| `chainlit_app.py` | セッションライフサイクル管理・メッセージハンドラ・要素の組み立て |
| `file_processor.py` | `process_files()` — アップロードファイルをプレーンテキストに解析 |
| `output_generator.py` | `to_csv()`・`to_excel()`・`to_pdf()` — `tool_results` からダウンロード用バイト列を生成 |

### 呼び出しチェーン

```
ユーザーメッセージ（Chainlit @on_message）
  └─► file_processor.process_files()          （アップロードファイルを解析 → テキストコンテキスト）
        └─► graph.ainvoke(AgentState)          （LangGraph、LangSmith RunnableConfig 付き）
              └─► [Think → Judge ループ]
                    └─► tool_results[]         （累積された MCP レスポンス）
                          ├─► output_generator.to_csv()    →  public/temp_files/
                          ├─► output_generator.to_excel()  →  public/temp_files/
                          ├─► _build_plotly()              →  cl.Plotly 要素
                          └─► output_generator.to_pdf()    →  public/temp_files/
```

---

## LangSmith トレーシング

**場所：** `.env`（環境変数） · `front_end/chainlit_app.py`（RunnableConfig）

LangGraph と LangChain には LangSmith トレーシングが**組み込み済み**のため、コード変更は不要です。  
3 つの環境変数を設定するだけで自動的に有効化されます。

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__xxxxxxxx
LANGCHAIN_PROJECT=fpt-fai-ai-chatbot
```

チャットメッセージ 1 件ごとに LangSmith に 1 つのルートトレースが作成され、ネストされたスパンが記録されます。

```
[ユーザーの質問]  （ルート run）
  └─► LangGraph
        ├─► think（イテレーション 1）
        │     ├─► ChatAnthropic  claude-sonnet-4-6   ← トークン数
        │     └─► MCP ツール呼び出し               ← レイテンシ・引数・出力
        └─► judge（イテレーション 1）
              └─► ChatAnthropic  claude-haiku-4-5    ← トークン数・評価結果
```

`chainlit_app.py` の `RunnableConfig` は各 run に `session_id` メタデータと `fpt-fai-ai-chatbot` タグを付与し、LangSmith ダッシュボードでのセッション別フィルタリングやコスト集計を可能にします。

---

## 環境変数

```bash
# Databricks
DATABRICKS_HOST=adb-xxxxxxxxxxxx.xx.azuredatabricks.net
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/xxxxxxxxxxxxxxxx
DATABRICKS_TOKEN=your_personal_access_token

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__xxxxxxxx
LANGCHAIN_PROJECT=fpt-fai-ai-chatbot
```

## クイックスタート

```bash
# フロントエンドの依存パッケージをインストール
cd front_end && pip install -r requirements.txt

# Chainlit を起動
chainlit run front_end/chainlit_app.py --port 8000
```
