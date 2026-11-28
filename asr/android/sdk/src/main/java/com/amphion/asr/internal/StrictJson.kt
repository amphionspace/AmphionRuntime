package com.amphion.asr.internal

/**
 * 授权文件专用的严格 JSON 解析器（纯 JVM，无 Android 依赖）。
 *
 * 为什么不用 org.json：Android 自带的 org.json 遇到重复键会静默覆盖，而签发端（Python）
 * 拒绝重复键。同一份签名字节在两端读出不同值，就可能让对账看到 seq=1、设备看到另一个值。
 * 这里重复键、浮点数、NaN、尾随内容、超深嵌套一律拒绝；整数按 Long 解析。
 */
internal object StrictJson {
    class JsonError(message: String) : IllegalArgumentException(message)

    private const val MAX_DEPTH = 16

    fun parse(text: String): Any? {
        val p = Parser(text)
        p.ws()
        val v = p.value(0)
        p.ws()
        if (p.i != text.length) throw JsonError("trailing content")
        return v
    }

    private class Parser(val s: String) {
        var i = 0

        fun ws() {
            while (i < s.length && (s[i] == ' ' || s[i] == '\n' || s[i] == '\r' || s[i] == '\t')) i++
        }

        fun value(depth: Int): Any? {
            if (depth > MAX_DEPTH) throw JsonError("too deep")
            if (i >= s.length) throw JsonError("unexpected end")
            return when (s[i]) {
                '{' -> obj(depth)
                '[' -> arr(depth)
                '"' -> str()
                't' -> lit("true", true)
                'f' -> lit("false", false)
                'n' -> lit("null", null)
                else -> num()
            }
        }

        fun lit(word: String, v: Any?): Any? {
            if (!s.startsWith(word, i)) throw JsonError("bad literal")
            i += word.length
            return v
        }

        fun obj(depth: Int): Map<String, Any?> {
            val out = LinkedHashMap<String, Any?>()
            i++
            ws()
            if (i < s.length && s[i] == '}') { i++; return out }
            while (true) {
                ws()
                if (i >= s.length || s[i] != '"') throw JsonError("expected key")
                val k = str()
                ws()
                if (i >= s.length || s[i] != ':') throw JsonError("expected colon")
                i++
                ws()
                if (out.containsKey(k)) throw JsonError("duplicate key")
                out[k] = value(depth + 1)
                ws()
                if (i >= s.length) throw JsonError("unexpected end")
                when (s[i]) {
                    ',' -> i++
                    '}' -> { i++; return out }
                    else -> throw JsonError("expected , or }")
                }
            }
        }

        fun arr(depth: Int): List<Any?> {
            val out = ArrayList<Any?>()
            i++
            ws()
            if (i < s.length && s[i] == ']') { i++; return out }
            while (true) {
                ws()
                out.add(value(depth + 1))
                ws()
                if (i >= s.length) throw JsonError("unexpected end")
                when (s[i]) {
                    ',' -> i++
                    ']' -> { i++; return out }
                    else -> throw JsonError("expected , or ]")
                }
            }
        }

        fun str(): String {
            i++
            val sb = StringBuilder()
            while (true) {
                if (i >= s.length) throw JsonError("unterminated string")
                val c = s[i++]
                when {
                    c == '"' -> return sb.toString()
                    c == '\\' -> {
                        if (i >= s.length) throw JsonError("bad escape")
                        when (val e = s[i++]) {
                            '"' -> sb.append('"'); '\\' -> sb.append('\\'); '/' -> sb.append('/')
                            'b' -> sb.append('\b'); 'f' -> sb.append('\u000C'); 'n' -> sb.append('\n')
                            'r' -> sb.append('\r'); 't' -> sb.append('\t')
                            'u' -> {
                                if (i + 4 > s.length) throw JsonError("bad unicode escape")
                                sb.append(s.substring(i, i + 4).toIntOrNull(16)?.toChar() ?: throw JsonError("bad unicode escape"))
                                i += 4
                            }
                            else -> throw JsonError("bad escape $e")
                        }
                    }
                    c < ' ' -> throw JsonError("control char in string")
                    else -> sb.append(c)
                }
            }
        }

        fun num(): Long {
            val start = i
            if (i < s.length && s[i] == '-') i++
            val digits = i
            while (i < s.length && s[i].isDigit()) i++
            if (i == digits) throw JsonError("bad number")
            if (s[digits] == '0' && i - digits > 1) throw JsonError("leading zero")
            if (i < s.length && (s[i] == '.' || s[i] == 'e' || s[i] == 'E')) throw JsonError("only integers allowed")
            return s.substring(start, i).toLongOrNull() ?: throw JsonError("integer overflow")
        }
    }
}
