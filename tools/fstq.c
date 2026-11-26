/* 直接用 GTKWave 的 FST 读取库（fstapi.c，随 Verilator 源码分发）做两种读法，
 * 作为 FST 的“原生读取”基准，避免把 pywellen 绑定的限制算到 FST 格式头上。
 *   fstq hier <file>              列出 句柄 位宽 全名
 *   fstq sig  <file> <句柄>       打印该信号的全部变化： 时间 值
 *   fstq time <file> <t>          打印 t 时刻每个句柄的值： 句柄 值
 * 编译：见 scripts/build_tools.sh
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fstapi.h"

static char **last;          /* time 模式：每个句柄最近的值 */
static uint64_t limit_t;

static void cb_sig(void *u, uint64_t t, fstHandle h, const unsigned char *v) {
    (void)u; (void)h;
    printf("%llu %s\n", (unsigned long long)t, v);
}
static void cb_time(void *u, uint64_t t, fstHandle h, const unsigned char *v) {
    (void)u;
    if (t > limit_t) return;
    size_t n = strlen((const char *)v);
    last[h] = realloc(last[h], n + 1);
    memcpy(last[h], v, n + 1);
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: fstq hier|sig|time <file> [arg]\n"); return 2; }
    void *ctx = fstReaderOpen(argv[2]);
    if (!ctx) { fprintf(stderr, "open failed\n"); return 1; }
    if (!strcmp(argv[1], "hier")) {
        struct fstHier *h; char scope[4096] = ""; size_t sl[256]; int d = 0;
        while ((h = fstReaderIterateHier(ctx))) {
            if (h->htyp == FST_HT_SCOPE) {
                sl[d++] = strlen(scope);
                if (scope[0]) strcat(scope, ".");
                strcat(scope, h->u.scope.name);
            } else if (h->htyp == FST_HT_UPSCOPE) {
                scope[sl[--d]] = 0;
            } else if (h->htyp == FST_HT_VAR) {
                printf("%u %u %s.%s\n", h->u.var.handle, h->u.var.length, scope, h->u.var.name);
            }
        }
    } else if (!strcmp(argv[1], "sig")) {
        fstReaderClrFacProcessMaskAll(ctx);
        fstReaderSetFacProcessMask(ctx, (fstHandle)atoi(argv[3]));
        fstReaderIterBlocks(ctx, cb_sig, NULL, NULL);
    } else {
        limit_t = strtoull(argv[3], NULL, 10);
        fstHandle mx = fstReaderGetMaxHandle(ctx);
        last = calloc(mx + 1, sizeof(char *));
        fstReaderSetFacProcessMaskAll(ctx);
        fstReaderSetLimitTimeRange(ctx, limit_t, limit_t);
        fstReaderIterBlocks(ctx, cb_time, NULL, NULL);
        for (fstHandle i = 1; i <= mx; i++) printf("%u %s\n", i, last[i] ? last[i] : "?");
    }
    fstReaderClose(ctx);
    return 0;
}
