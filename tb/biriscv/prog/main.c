/* 本项目自己写的裸机负载（不是标准基准）：排序 + CRC32 + 矩阵乘 + 除法，无限循环。
   目的只是让处理器做一段有分支、有访存、有乘除的持续计算，用来产生波形。 */
#define N 128
static unsigned int a[N];
static unsigned char buf[512];
static int ma[8][8], mb[8][8], mc[8][8];
static unsigned int seed = 0x12345678u;
volatile unsigned int sink;

static unsigned int rnd(void) {
    seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
    return seed;
}

static void sort(void) {
    for (int i = 1; i < N; i++) {
        unsigned int k = a[i]; int j = i - 1;
        while (j >= 0 && a[j] > k) { a[j + 1] = a[j]; j--; }
        a[j + 1] = k;
    }
}

static unsigned int crc32(const unsigned char *p, int n) {
    unsigned int c = 0xffffffffu;
    for (int i = 0; i < n; i++) {
        c ^= p[i];
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & -(c & 1));
    }
    return ~c;
}

static void matmul(void) {
    for (int i = 0; i < 8; i++)
        for (int j = 0; j < 8; j++) {
            int s = 0;
            for (int k = 0; k < 8; k++) s += ma[i][k] * mb[k][j];
            mc[i][j] = s;
        }
}

int main(void) {
    for (;;) {
        for (int i = 0; i < N; i++) a[i] = rnd();
        sort();
        for (int i = 0; i < 512; i++) buf[i] = (unsigned char)rnd();
        sink = crc32(buf, 512);
        for (int i = 0; i < 8; i++)
            for (int j = 0; j < 8; j++) { ma[i][j] = (int)(rnd() & 0xff) - 128; mb[i][j] = (int)(rnd() & 0xff) - 128; }
        matmul();
        unsigned int d = 0;
        for (int i = 0; i < 64; i++) d += a[i] / ((a[N - 1 - i] >> 20) | 1u) + (unsigned int)mc[i & 7][(i >> 3) & 7] % 7u;
        sink = d + a[0];
    }
}
