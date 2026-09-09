"""Allowlisted error metadata: never persist provider messages, prompts or credentials."""
import re

API_CODES={'invalid_api_key','insufficient_quota','rate_limit_exceeded','model_not_found',
           'permission_denied','unsupported_country_region_territory','unsupported_parameter',
           'unsupported_value','invalid_json_schema','invalid_request_error','billing_hard_limit_reached'}
LOCAL_CODES={'redirect_rejected','invalid_endpoint','response_too_large','transport_or_json_error',
 'timeout','tls_error','dns_error','connection_error','invalid_format','not_configured',
 'refused_or_incomplete','invalid_content','invalid_response','schema_invalid','ungrounded_risk',
 'ungrounded_observation','unverified_observation','invalid_ranking','invalid_citation',
 'invalid_embedding_response','embedding_dimension_changed','zero_vector','invalid_threshold'}

def safe_error(exc):
    code=exc.args[0] if exc.args and isinstance(exc.args[0],str) else 'internal_validation_error'
    if code not in LOCAL_CODES and not re.fullmatch(r'http_[1-5]\d\d',code): code='internal_validation_error'
    result={'code':code}
    api_code=getattr(exc,'api_code',None)
    if api_code in API_CODES: result['api_code']=api_code
    reason=api_code or code
    if reason=='invalid_api_key' or code=='http_401': hint='API 身份验证失败。请检查密钥是否完整、有效，以及是否属于 OpenAI 官方 API。'
    elif reason in ['insufficient_quota','billing_hard_limit_reached']: hint='API 额度或账单限制。请检查 OpenAI API 项目的可用额度和用量上限。'
    elif reason=='model_not_found': hint='当前模型不存在或该 API 项目没有访问权限；需要核对模型可用性。'
    elif reason=='unsupported_country_region_territory': hint='服务返回地区不支持。请核对官方 API 支持地区。'
    elif code=='http_429': hint='请求被限流或额度不足；请结合 api_code 检查 API 用量和账单。'
    elif code=='http_403': hint='请求被拒绝；需要核对 API 项目权限及服务访问条件。'
    elif code=='http_404': hint='接口或模型不可用；需核对接口路径与模型权限。'
    elif code=='timeout': hint='请求超时；尚不能据此判断密钥是否有效。'
    elif code=='tls_error': hint='HTTPS 证书验证失败；请检查本机证书、网络及代理设置。'
    elif code=='dns_error': hint='无法解析服务域名；请检查本机网络和 DNS。'
    elif code=='connection_error': hint='未能建立服务连接；请检查本机网络或代理。'
    elif code in ['schema_invalid','invalid_ranking','invalid_citation','ungrounded_observation','unverified_observation','ungrounded_risk']:
        hint='接口返回了结果，但未通过本地证据或格式校验；这不等同于密钥错误。'
    elif code=='http_400': hint='接口拒绝请求参数；需要核对模型与结构化输出格式支持。'
    else: hint='需要按错误代码进一步排查；当前保持离线降级。'
    result['hint']=hint
    return result
