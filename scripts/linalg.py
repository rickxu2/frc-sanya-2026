"""
Tiny dependency-free linear algebra for OPR-style least squares.

OPR (Offensive Power Rating) and its component variants are the least-squares
solution to  A x = b , where:
    - each row of A is one alliance's appearance in one match
      (1.0 in the columns of the 3 teams on that alliance, 0 elsewhere)
    - b is that alliance's value of the metric in that match
      (total score, auto points, fuel scored, tower points, ...)
    - x is the per-team contribution we solve for (the OPR of that metric).

We solve the normal equations  (A^T A) x = A^T b  with Gaussian elimination
and partial pivoting. A^T A is (nTeams x nTeams), tiny for one event, so this
is fast and needs no numpy.
"""


def build_normal_equations(rows, n):
    """rows: list of (indices, value). indices = list of team-column ints.
    Returns (AtA, Atb) where AtA is n x n, Atb is length n."""
    AtA = [[0.0] * n for _ in range(n)]
    Atb = [0.0] * n
    for idxs, val in rows:
        for i in idxs:
            Atb[i] += val
            for j in idxs:
                AtA[i][j] += 1.0
    return AtA, Atb


def solve(AtA, Atb, ridge=1e-6):
    """Solve (AtA + ridge*I) x = Atb via Gaussian elimination w/ partial pivot.
    A small ridge term keeps the system stable when a team plays very few
    matches or the design is near-singular."""
    n = len(Atb)
    # Copy + add ridge on the diagonal for numerical stability.
    M = [row[:] for row in AtA]
    b = Atb[:]
    for i in range(n):
        M[i][i] += ridge

    for col in range(n):
        # partial pivot
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            continue  # singular column; leave as 0
        if pivot != col:
            M[col], M[pivot] = M[pivot], M[col]
            b[col], b[pivot] = b[pivot], b[col]
        piv = M[col][col]
        for r in range(n):
            if r == col:
                continue
            factor = M[r][col] / piv
            if factor == 0.0:
                continue
            for c in range(col, n):
                M[r][c] -= factor * M[col][c]
            b[r] -= factor * b[col]
    x = [0.0] * n
    for i in range(n):
        if abs(M[i][i]) > 1e-12:
            x[i] = b[i] / M[i][i]
    return x


def opr(alliance_rows, team_index, ridge=1e-6):
    """alliance_rows: list of (team_numbers_tuple, value).
    team_index: dict team_number -> column int.
    Returns dict team_number -> opr value for this metric."""
    n = len(team_index)
    rows = []
    for teams, val in alliance_rows:
        idxs = [team_index[t] for t in teams if t in team_index]
        if not idxs:
            continue
        rows.append((idxs, float(val)))
    if not rows:
        return {t: 0.0 for t in team_index}
    AtA, Atb = build_normal_equations(rows, n)
    x = solve(AtA, Atb, ridge=ridge)
    inv = {v: k for k, v in team_index.items()}
    return {inv[i]: x[i] for i in range(n)}
