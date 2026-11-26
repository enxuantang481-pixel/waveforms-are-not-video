/* libfst 的进程内读取外壳，编成共享库给 Python ctypes 调用（不起子进程，不走文本管道）。
 * 编译：见 scripts/build_tools.sh
 *   fq_open / fq_close
 *   fq_hier(ctx)                返回一段文本：每行“句柄 位宽 全名”，和 fstq hier 相同
 *   fq_sig(ctx, h, &t, &v)      读一个句柄的全部变化；t 是 uint64 数组，v 是 n*位宽 个 ASCII 字符；返回 n
 *   fq_time(ctx, t, off, out)   读 t 时刻全部句柄的值，写进 out[off[h] ...]（ASCII 字符，off 由调用方按位宽累加）
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fstapi.h"

static char *hbuf; static size_t hlen, hcap;
static uint64_t *tb; static unsigned char *vb; static size_t n_, cap_, w_;
static const uint64_t *off_; static unsigned char *out_; static uint64_t lim_;

void *fq_open(const char *p) { return fstReaderOpen(p); }
void fq_close(void *c) { fstReaderClose(c); }
unsigned fq_max_handle(void *c) { return fstReaderGetMaxHandle(c); }

const char *fq_hier(void *ctx) {
    struct fstHier *h; char scope[4096] = ""; size_t sl[256]; int d = 0;
    hlen = 0;
    fstReaderIterateHierRewind(ctx);
    while ((h = fstReaderIterateHier(ctx))) {
        if (h->htyp == FST_HT_SCOPE) {
            sl[d++] = strlen(scope);
            if (scope[0]) strcat(scope, ".");
            strcat(scope, h->u.scope.name);
        } else if (h->htyp == FST_HT_UPSCOPE) {
            scope[sl[--d]] = 0;
        } else if (h->htyp == FST_HT_VAR) {
            size_t need = strlen(scope) + strlen(h->u.var.name) + 64;
            if (hlen + need > hcap) { hcap = (hcap + need) * 2; hbuf = realloc(hbuf, hcap); }
            hlen += sprintf(hbuf + hlen, "%u %u %s.%s\n", h->u.var.handle, h->u.var.length, scope, h->u.var.name);
        }
    }
    if (!hbuf) { hbuf = malloc(1); }
    hbuf[hlen] = 0;
    return hbuf;
}

static void cb_sig(void *u, uint64_t t, fstHandle h, const unsigned char *v) {
    (void)u; (void)h;
    if (n_ == cap_) { cap_ = cap_ ? cap_ * 2 : 4096; tb = realloc(tb, cap_ * 8); vb = realloc(vb, cap_ * w_); }
    tb[n_] = t; memcpy(vb + n_ * w_, v, w_); n_++;
}
size_t fq_sig(void *ctx, unsigned h, unsigned width, uint64_t **t, unsigned char **v) {
    free(tb); free(vb); tb = NULL; vb = NULL; n_ = cap_ = 0; w_ = width;
    fstReaderClrFacProcessMaskAll(ctx);
    fstReaderSetFacProcessMask(ctx, h);
    fstReaderIterBlocks(ctx, cb_sig, NULL, NULL);
    *t = tb; *v = vb;
    return n_;
}

static void cb_time(void *u, uint64_t t, fstHandle h, const unsigned char *v) {
    (void)u;
    if (t > lim_) return;
    memcpy(out_ + off_[h], v, off_[h + 1] - off_[h]);
}
void fq_time(void *ctx, uint64_t t, const uint64_t *off, unsigned char *out) {
    off_ = off; out_ = out; lim_ = t;
    fstReaderSetFacProcessMaskAll(ctx);
    fstReaderSetLimitTimeRange(ctx, t, t);
    fstReaderIterBlocks(ctx, cb_time, NULL, NULL);
}
