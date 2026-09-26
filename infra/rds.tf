# ===== RDS for MySQL =====

# DBのパスワードはランダムに生成し、SSMパラメータストアに暗号化して保存する(Gitには含めない)
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_ssm_parameter" "db_password" {
  name        = "/${var.project}/db/password"
  description = "RDS for MySQL のアプリ用パスワード"
  type        = "SecureString"
  value       = random_password.db.result
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.project}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${var.project}-db-subnet-group" }
}

resource "aws_db_instance" "main" {
  identifier = "${var.project}-db"

  engine         = "mysql"
  engine_version = "8.4"
  instance_class = var.db_instance_class

  allocated_storage = 20
  storage_type      = "gp2"
  storage_encrypted = true

  db_name  = "kakeibo"
  username = "kakeibo"
  password = random_password.db.result

  # プライベートサブネットに配置し、インターネットからは接続できないようにする
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false

  # 費用を抑える設定(自動バックアップは1日分のみ、追加の監視機能は使わない)
  backup_retention_period      = 1
  performance_insights_enabled = false
  monitoring_interval          = 0

  # 学習用のため、削除時の最終スナップショットは作らない
  skip_final_snapshot = true
  deletion_protection = false
  apply_immediately   = true

  tags = { Name = "${var.project}-db" }
}
