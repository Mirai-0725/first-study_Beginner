variable "region" {
  description = "AWSのリージョン"
  type        = string
  default     = "ap-northeast-1"
}

variable "project" {
  description = "リソース名の先頭に付ける名前"
  type        = string
  default     = "kakeibo"
}

variable "allowed_cidr" {
  description = "アプリ(HTTP)へのアクセスを許可するIPアドレス範囲。自分のグローバルIPアドレスを /32 で指定する(例: 203.0.113.10/32)"
  type        = string

  validation {
    condition     = can(cidrhost(var.allowed_cidr, 0)) && var.allowed_cidr != "0.0.0.0/0"
    error_message = "CIDR形式で指定してください。アプリにログイン機能がないため 0.0.0.0/0(全開放)は指定できません。"
  }
}

variable "instance_type" {
  description = "EC2のインスタンスタイプ(無料プランの対象から選ぶ)"
  type        = string
  default     = "t4g.micro"
}

variable "db_instance_class" {
  description = "RDSのインスタンスクラス(無料プランの対象から選ぶ)"
  type        = string
  default     = "db.t4g.micro"
}

variable "repository_url" {
  description = "EC2にデプロイするアプリのGitリポジトリ(公開リポジトリ)"
  type        = string
  default     = "https://github.com/Mirai-0725/first-study_Beginner.git"
}

variable "repository_branch" {
  description = "デプロイするブランチ"
  type        = string
  default     = "main"
}
