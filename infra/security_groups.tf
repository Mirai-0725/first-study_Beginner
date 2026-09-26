# ===== EC2 のセキュリティグループ =====

resource "aws_security_group" "app" {
  name        = "${var.project}-app-sg"
  description = "EC2 (Nginx + Django)"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-app-sg" }
}

# アプリにログイン機能がないため、HTTP は自分のIPアドレスからのみ許可する
resource "aws_vpc_security_group_ingress_rule" "app_http" {
  security_group_id = aws_security_group.app.id
  description       = "HTTP from allowed CIDR only"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = var.allowed_cidr
}

# SSH(22)は開けない。管理用の接続には SSM セッションマネージャーを使う

# パッケージのインストール・GitHubからの取得・RDSへの接続のため、送信はすべて許可する
resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  description       = "All outbound"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ===== RDS のセキュリティグループ =====

resource "aws_security_group" "db" {
  name        = "${var.project}-db-sg"
  description = "RDS for MySQL (from app SG only)"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-db-sg" }
}

# MySQL(3306)は EC2 のセキュリティグループからのみ許可する(IPアドレスではなくSGで指定)
resource "aws_vpc_security_group_ingress_rule" "db_mysql_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "MySQL from app SG only"
  ip_protocol                  = "tcp"
  from_port                    = 3306
  to_port                      = 3306
  referenced_security_group_id = aws_security_group.app.id
}
