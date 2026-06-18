{{/* 通用名 helpers，与 helm create 模板风格一致 */}}

{{- define "asr-service.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "asr-service.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "asr-service.labels" -}}
app.kubernetes.io/name: {{ include "asr-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "asr-service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "asr-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
