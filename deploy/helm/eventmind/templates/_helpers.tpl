{{/* Базовое имя релиза. */}}
{{- define "eventmind.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "eventmind.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s" (include "eventmind.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "eventmind.labels" -}}
app.kubernetes.io/name: {{ include "eventmind.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/* Общие env-переменные из ConfigMap+Secret для backend-процессов. */}}
{{- define "eventmind.backendEnv" -}}
- name: ENVIRONMENT
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: ENVIRONMENT } }
- name: LOG_LEVEL
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: LOG_LEVEL } }
- name: LOG_JSON
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: LOG_JSON } }
- name: CORS_ORIGINS
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: CORS_ORIGINS } }
- name: PUBLIC_WEB_URL
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: PUBLIC_WEB_URL } }
- name: API_INTERNAL_URL
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: API_INTERNAL_URL } }
- name: SMTP_HOST
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: SMTP_HOST } }
- name: SMTP_PORT
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: SMTP_PORT } }
- name: SMTP_USE_TLS
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: SMTP_USE_TLS } }
- name: SMTP_USE_SSL
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: SMTP_USE_SSL } }
- name: EMAIL_FROM
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: EMAIL_FROM } }
- name: TELEGRAM_BOT_USERNAME
  valueFrom: { configMapKeyRef: { name: {{ include "eventmind.fullname" . }}-config, key: TELEGRAM_BOT_USERNAME } }
- name: DATABASE_URL
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: DATABASE_URL } }
- name: REDIS_URL
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: REDIS_URL } }
- name: JWT_SECRET
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: JWT_SECRET } }
- name: API_SHARED_SECRET
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: API_SHARED_SECRET } }
- name: GOOGLE_API_KEY
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: GOOGLE_API_KEY } }
- name: GROQ_API_KEY
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: GROQ_API_KEY } }
- name: GOOGLE_OAUTH_CLIENT_ID
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: GOOGLE_OAUTH_CLIENT_ID } }
- name: SMTP_USER
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: SMTP_USER } }
- name: SMTP_PASSWORD
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: SMTP_PASSWORD } }
- name: BOT_TOKEN
  valueFrom: { secretKeyRef: { name: {{ include "eventmind.fullname" . }}-secrets, key: BOT_TOKEN } }
{{- end -}}
