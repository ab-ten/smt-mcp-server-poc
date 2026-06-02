# Secure MCP Tunnel MCP Server PoC

ローカルワークスペース内のテキストファイルを読み取り専用で参照するための MCP サーバー PoC です。

Docker コンテナ内で Python 製の MCP サーバーを起動し、`tunnel-client` を通じて Secure Tunneling のトンネルに接続します。公開される操作はファイル一覧、ファイル検索、ファイル読み取り、テキスト検索に限定されています。

## 主な機能

- ワークスペース配下のファイルとディレクトリの一覧取得
- ワイルドカードによるファイル検索
- UTF-8 テキストファイルの行単位読み取り
- UTF-8 テキストファイル内の文字列検索
- `.cmd` / `.bat` ファイルの CP932 フォールバック読み取り
- シンボリックリンク、親ディレクトリ参照、絶対パスの拒否
- 秘密情報やバイナリに該当しやすいファイル名・拡張子の除外

## ディレクトリ構成

```text
.
├── Dockerfile
├── build.cmd
├── run.cmd
├── requirements.txt
├── app
│   ├── entrypoint.sh
│   └── server.py
└── bin
    └── tunnel-client （別途ダウンロードしてください）
```

| パス | 説明 |
| --- | --- |
| `app/server.py` | MCP サーバー本体です。読み取り専用のファイル操作ツールを定義します。 |
| `app/entrypoint.sh` | `tunnel-client` の初期化と実行を行うコンテナ起動スクリプトです。 |
| `bin/tunnel-client` | Secure Tunneling 接続に使用する実行ファイルです。 |
| `Dockerfile` | Python 3.12 slim ベースのコンテナイメージを定義します。 |
| `build.cmd` | Windows 環境向けの Docker イメージビルド用スクリプトです。 |
| `run.cmd` | Windows 環境向けの Docker コンテナ起動用スクリプトです。 |
| `requirements.txt` | Python 依存関係を定義します。 |

## 前提条件

- Docker
- Secure Tunneling のトンネル ID
- Secure Tunneling の API キー
- Windows で `build.cmd` / `run.cmd` を使用する場合は、コマンドプロンプトから実行できる Docker 環境

## セットアップ

### 1. tunnel-client の配置

`tunnel-client` はリポジトリに含めません。GitHub Releases から Linux 用の実行バイナリを取得し、展開後の実行ファイルを `bin/tunnel-client` として配置してください。

取得元:

- https://github.com/openai/tunnel-client/releases

配置後の構成は次のとおりです。

```text
bin/
└── tunnel-client
```

### 2. Docker イメージのビルド

Windows では次のコマンドを実行します。

```cmd
build.cmd
```

実行される Docker コマンドは次のとおりです。

```cmd
docker build -t smt-local-files-mcp .
```

### 3. 環境変数の設定

`app/entrypoint.sh` は、次の環境変数を必須として扱います。

| 環境変数 | 必須 | 説明 |
| --- | --- | --- |
| `CONTROL_PLANE_API_KEY` | はい | Secure Tunneling の API キーです。 |
| `TUNNEL_ID` | はい | 接続先トンネルの ID です。 |
| `MCP_ROOT` | いいえ | MCP サーバーが参照するワークスペースのルートです。既定値は `/workspace` です。 |
| `MAX_READ_BYTES` | いいえ | `read_file` で読み取り可能な最大ファイルサイズです。既定値は `262144` です。 |
| `MAX_SCAN_BYTES` | いいえ | `search_text` で走査可能な最大ファイルサイズです。既定値は `1048576` です。 |
| `MAX_RESULTS` | いいえ | 検索系ツールの最大結果件数です。既定値は `100` です。 |
| `ALLOW_EXTS` | いいえ | 読み取り対象として許可する拡張子のカンマ区切りリストです。未指定時はソースコード、設定ファイル、ドキュメント系の拡張子が許可されます。 |

`run.cmd` は、リポジトリルートに `.env` が存在する場合に `--env-file` として読み込みます。

`.env` の例は次のとおりです。

```env
CONTROL_PLANE_API_KEY=your_api_key
TUNNEL_ID=your_tunnel_id
```

## 実行方法

Windows では次のコマンドを実行します。

```cmd
run.cmd
```

`run.cmd` は、現在のディレクトリを `/workspace` に読み取り専用でマウントし、`app` ディレクトリを `/app` にマウントします。

```cmd
docker run --rm -it --env-file ".env" -v "%CD%\app:/app" -v "%CD%:/workspace:ro" -e MCP_ROOT=/workspace smt-local-files-mcp
```

実際の `run.cmd` では、スクリプトの配置場所に基づいて `app` ディレクトリをマウントします。また、追加の Docker オプションは `run.cmd` の引数として渡せます。

## MCP ツール

### `list_files`

ワークスペース配下のファイルとディレクトリを一覧表示します。

主な引数:

- `path`: 一覧表示する相対パスです。既定値は空文字です。
- `recursive`: 再帰的に走査するかどうかを指定します。既定値は `false` です。
- `max_entries`: 最大件数です。1 から 1000 の範囲に丸められます。

### `find_files`

シェル形式のワイルドカードパターンでファイルを検索します。

主な引数:

- `pattern`: 検索パターンです。
- `path`: 検索対象の相対パスです。既定値は空文字です。
- `max_results`: 最大件数です。

### `read_file`

UTF-8 テキストファイルを行単位で読み取ります。`.cmd` / `.bat` ファイルは、UTF-8 として読み込めない場合に CP932 として読み込みます。

主な引数:

- `path`: 読み取り対象の相対パスです。
- `start_line`: 読み取り開始行です。既定値は `1` です。
- `max_lines`: 読み取り最大行数です。1 から 2000 の範囲に丸められます。

### `search_text`

UTF-8 テキストファイル内の文字列を検索します。`.cmd` / `.bat` ファイルは、UTF-8 として読み込めない場合に CP932 として読み込みます。

主な引数:

- `query`: 検索文字列または正規表現です。
- `path`: 検索対象の相対パスです。既定値は空文字です。
- `regex`: `query` を正規表現として扱うかどうかを指定します。既定値は `false` です。
- `case_sensitive`: 大文字小文字を区別するかどうかを指定します。既定値は `false` です。
- `max_results`: 最大件数です。

## セキュリティ制限

このサーバーは読み取り専用として設計されています。次の制限により、意図しないファイル参照を抑制します。

- 絶対パスは許可されません。
- `..` による親ディレクトリ参照は許可されません。
- シンボリックリンクは追跡されません。
- `.git`、`node_modules`、仮想環境、ビルド出力などのディレクトリは走査対象から除外されます。
- `.env`、秘密鍵、認証設定ファイルなどは読み取り対象から除外されます。
- `.pem`、`.key`、`.sqlite`、`.db` などの拡張子は読み取り対象から除外されます。
- UTF-8 としてデコードできないファイル、NUL バイトを含むファイル、サイズ上限を超えるファイルは読み取られません。ただし、`.cmd` / `.bat` ファイルは CP932 での読み込みも試行されます。

## Secure Tunneling 側の準備

Secure Tunneling 側では、サービスアカウントと API キーを作成し、トンネルの利用権限を付与する必要があります。

準備例:

- Secure Tunneling 用のプロジェクトを作成します。
- トンネル利用用のサービスアカウントを作成します。
- サービスアカウントにトンネルの Read/Use 権限を付与します。
- 組織またはプロジェクトで API キーを発行します。
- サービスアカウントに必要なロールを設定します。

具体的なロール名や権限設定は、利用している Secure Tunneling 環境の管理画面に合わせて確認してください。

## 注意事項

- `Dockerfile` では `app/server.py` と `app/entrypoint.sh` をイメージ内へコピーしていません。現状の `run.cmd` は `app` ディレクトリを `/app` にマウントして実行する構成です。
- Linux や macOS で利用する場合は、`run.cmd` と同等の `docker run` コマンドまたはシェルスクリプトを用意してください。
- `bin/tunnel-client` は実行ファイルのため、配布・更新方法や対応プラットフォームを別途管理してください。
- `.env` には API キーなどの秘密情報が含まれるため、リポジトリへコミットしないでください。
