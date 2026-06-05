# ChatGPT App・Secure MCP Tunnel・Cognito 構築手順

## project scope の tunnel-client 用 API キーの作成方法
- SecureTunneling project 作成
- organization:people:role "tunnel user service account" 作成, Tunnels=Read/Use
- organization:API Keys:create new secret key, service account = SecureTunneling, name = secure-mcp-tunnel
- SecureTunnel プロジェクト内と organization 内に secure-mcp-tunnel サービスアカウントユーザーが作成される
- project SecureTunnel:people:members:secure-mcp-tunnel roles を サービスアカウントの roles に viewer (preset) を設定
- organization:people:secure-mcp-tunnel サービスアカウントの roles に User (preset) と tunnel user service account を設定

## MCP ユーザー認証用 Cognito User Pool 作成
- 自分で管理して自分だけで使う IdP という運用体制。Cognito 管理画面でユーザーを追加する運用。
- region を決めて cognito → user pool → 作成
  - application type: 従来のWebアプリケーション
  - アプリケーション名決定: chatgpt-mcp （例）
  - オプション: メールアドレスのみ, 自己登録不可、属性に email を追加。
  - リターンURL: 追加しなくて良い（後で追加する）
  - ユーザープールIDを .env COGNITO_USER_POOL_ID= に設定
- 作成したユーザープール → ブランディング → ドメイン
  - Cognito ドメインがここで取得できる。後で利用。
    - Authorization URL: `https://<Cognitoドメイン>/oauth2/authorize`
    - Token URL: `https://<Cognitoドメイン>/oauth2/token`
- 作成したユーザープール → アプリケーション → リソースサーバー
  - リソースサーバーを作成
    - リソースサーバー名: chatgpt-mcp-auth （例）
    - リソースサーバー識別子: chatgpt-mcp-auth （例）後で変更できない。aud を使いたい場合はURLにする
    - カスタムスコープを追加: スコープ名 invoke、説明「呼び出し権限」
- 作成したユーザープール → ユーザー管理 → ユーザー → ユーザーを作成
  - 自分用ユーザーを作成する
    - 招待を送信しない
    - Eメールアドレス: 自分のEメールアドレスを入力。検証済みとしてマークする。
  - Eメールアドレスは実際のメールアドレスでなくても良いが、その場合はパスワードの設定で初期パスワードを設定する事
  - ユーザーIDとしてUUID文字列が設定されるので .env の COGNITO_ALLOWED_SUB= に設定する。
- 作成したユーザープール → アプリケーションクライアント
  - デフォルトで一つ作成されていると思うが、なかった場合は作成する。
  - クライアントIDとシークレットは後で使用する
  - 作成したクライアント → ログインページ からログインページが表示されることを確認しておく
    - スタイルが割り当てられていないと表示されないので、ない場合はスタイルを作成して割り当てる
  - 作成したクライアント → 属性権限
    - 読み込みは email 以外全削除
    - 書き込みも設定可能なものは全削除

## ChatGPT
- 設定 → アプリ
- 高度な設定 → 開発者モード on
- アプリを作成（後から修正するには作り直しになります）
  - 名前: home-mcp-service （例）
  - 説明: 適当に
  - 接続: トンネルを選択
    - トンネルIDを入力で作成した tunnel_id を入力
  - 認証: OAuth
  - 「理解したうえで、続行します」を理解したうえでチェック
  - OAuthの詳細設定をクリック
    - 登録方法: ユーザー定義のOAuthクライアント
    - コールバックURLをメモ
      - Cognito のアプリケーションクライアント → ログインページ → 編集
      - 許可されているコールバック URL に ChatGPT側のコールバックURLを設定
      - OAuth 2.0 許可タイプ: 認証コード付与
      - カスタムスコープ: `<リソースサーバー識別子>/invoke`
    - OAuth クライアントID: アプリケーションクライアントのクライアントIDを設定
      - .env の COGNITO_CLIENT_ID= にも同じものを設定
    - OAuth クライアントシークレット: アプリケーションクライアントのシークレットを設定
    - トークンエンドポイントの認証方法: client_secret_post
    - デフォルトのスコープ: `<リソースサーバー識別子>/invoke`
      - .env の COGNITO_REQUIRED_SCOPES= にも同じものを設定
    - 認証URL: `<Authorization URL>`
    - トークンURL: `<Token URL>`
