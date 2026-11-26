"""信号（比特）排序。返回长度 B 的排列 order：排列后的第 j 行是规范矩阵的第 order[j] 行。"""
import numpy as np


def _toggle_features(m, nwin=512):
    """每个比特在每个时间窗口里的翻转次数，(B, nwin) float32。"""
    edges = np.linspace(0, m.T - 1, nwin + 1).astype(int)
    F = np.zeros((m.B, nwin), dtype=np.float32)
    for b in range(m.B):
        r = m.row(b)
        tg = np.flatnonzero(r[1:] != r[:-1])
        if len(tg):
            F[b] = np.histogram(tg, bins=edges)[0]
    return F


def _cluster(F, metric):
    """对特征行做层次聚类，返回叶子顺序。全零（或常数）行放到最后。"""
    from scipy.cluster.hierarchy import leaves_list, linkage
    active = np.flatnonzero(F.std(axis=1) > 0)
    rest = np.setdiff1d(np.arange(F.shape[0]), active)
    if len(active) > 2:
        Z = linkage(F[active], method="average", metric=metric)
        active = active[leaves_list(Z)]
    return np.concatenate([active, rest])


def make_order(m, kind, seed=1):
    if kind == "hier":
        return None
    if kind == "random":
        return np.random.default_rng(seed).permutation(m.B)
    F = _toggle_features(m)
    if kind == "toggle":            # 按翻转总数从多到少
        return np.argsort(-F.sum(axis=1), kind="stable")
    if kind == "cluster_toggle":    # 翻转的时间分布相似的排在一起
        return _cluster(np.log1p(F), "correlation")
    if kind == "cluster_value":     # 取值相似的排在一起（均匀抽 2048 个周期，汉明距离）
        ts = np.linspace(0, m.T - 1, 2048).astype(int)
        V = np.stack([m.row(b)[ts] for b in range(m.B)]).astype(np.float32)
        order = _cluster(V, "hamming")
        return order
    raise ValueError(kind)
