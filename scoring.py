"""Territory scoring and conservative, bounded automatic dead-group reading.

Only proven enclosed captures are marked. Ko, large unsettled fights, and search
budget exhaustion remain for review; they are never silently declared dead.
"""
N = 13


def adjacent(i):
    x, y = i % N, i // N
    return [j for j in (i-1 if x else -1, i+1 if x < N-1 else -1,
                        i-N if y else -1, i+N if y < N-1 else -1) if j >= 0]


def group(board, start):
    stones, liberties, todo = {start}, set(), [start]
    while todo:
        for j in adjacent(todo.pop()):
            if board[j] == 0:
                liberties.add(j)
            elif board[j] == board[start] and j not in stones:
                stones.add(j); todo.append(j)
    return stones, liberties


def regions(board):
    visited = set()
    for i, value in enumerate(board):
        if value or i in visited:
            continue
        points, border, todo = {i}, set(), [i]
        visited.add(i)
        while todo:
            for j in adjacent(todo.pop()):
                if board[j]:
                    border.add(j)
                elif j not in visited:
                    visited.add(j); points.add(j); todo.append(j)
        yield points, border


def pass_alive(board):
    """Benson fixed point: groups with two surviving vital regions."""
    alive = set()
    for color in (1, -1):
        groups, seen = {}, set()
        for i, value in enumerate(board):
            if value == color and i not in seen:
                stones, libs = group(board, i)
                groups[i] = (stones, libs); seen.update(stones)
        owner = {p: key for key, (stones, _) in groups.items() for p in stones}
        eyes = [(points, {owner[p] for p in border}) for points, border in regions(board)
                if border and all(board[p] == color for p in border)]
        remaining = set(groups)
        while True:
            valid = [(points, bounds) for points, bounds in eyes if bounds <= remaining]
            keep = {key for key in remaining if sum(points <= groups[key][1] for points, _ in valid) >= 2}
            if keep == remaining:
                break
            remaining = keep
        for key in remaining:
            alive.update(groups[key][0])
    return alive


def automatic_dead(board):
    """Read small pockets surrounded entirely by proven live enemy stones."""
    safe = pass_alive(board)
    dead, uncertain, seen = set(), set(), set()
    budget = [12000]
    for i, color in enumerate(board):
        if not color or i in seen:
            continue
        stones, _ = group(board, i); seen.update(stones)
        if stones <= safe:
            continue
        pocket, border, todo = set(stones), set(), list(stones)
        while todo:
            for j in adjacent(todo.pop()):
                if board[j] == -color:
                    border.add(j)
                elif j not in pocket:
                    pocket.add(j); todo.append(j)
        if len(pocket) > 9 or not border or not border <= safe:
            uncertain.update(stones); continue

        def captured(position, turn, passes, path, depth):
            if not any(position[p] == color for p in stones):
                return True
            if passes == 2:
                return False
            key = (tuple(position), turn)
            if key in path or depth > 24 or budget[0] <= 0:
                return None
            budget[0] -= 1
            outcomes = []
            for point in pocket:
                if position[point]:
                    continue
                next_board = position.copy(); next_board[point] = turn
                for j in adjacent(point):
                    if next_board[j] == -turn:
                        enemy, libs = group(next_board, j)
                        if not libs:
                            for p in enemy:
                                next_board[p] = 0
                if not group(next_board, point)[1]:
                    continue
                # Never read through capture of an enclosing group or ko cycle.
                if any(next_board[p] != board[p] for p in border):
                    outcomes.append(None); continue
                result = captured(next_board, -turn, 0, path | {key}, depth+1)
                outcomes.append(result)
                if turn == -color and result is True:
                    return True
                if turn == color and result is False:
                    return False
            outcomes.append(captured(position, -turn, passes+1, path | {key}, depth+1))
            if turn == -color:
                return True if True in outcomes else None if None in outcomes else False
            return False if False in outcomes else None if None in outcomes else True

        # Defender moves first. Only forced death earns an automatic mark.
        if captured(board, color, 0, set(), 0) is True:
            dead.update(stones)
        else:
            uncertain.update(stones)
    return dead, uncertain


def territory_score(board, dead, captures, komi=6.5):
    clean = [0 if i in dead else value for i, value in enumerate(board)]
    ownership = list(regions(clean))
    # Japanese rules exclude eyes belonging to groups with shared dame (seki).
    seki_groups = set()
    for _, border in ownership:
        if {clean[p] for p in border} == {1, -1}:
            for p in border:
                if p not in seki_groups:
                    seki_groups.update(group(clean, p)[0])
    territory = {1: 0, -1: 0}; neutral = 0
    for points, border in ownership:
        colors = {clean[p] for p in border}
        if len(colors) == 1 and not border & seki_groups:
            territory[next(iter(colors))] += len(points)
        else:
            neutral += len(points)
    prisoners = {'black': captures['black'] + sum(board[i] == -1 for i in dead),
                 'white': captures['white'] + sum(board[i] == 1 for i in dead)}
    black = territory[1] + prisoners['black']
    white = territory[-1] + prisoners['white'] + komi
    return dict(black=black, white=white, komi=komi, blackTerritory=territory[1],
                whiteTerritory=territory[-1], blackPrisoners=prisoners['black'],
                whitePrisoners=prisoners['white'], neutral=neutral,
                winner='black' if black > white else 'white', margin=round(abs(black-white), 1),
                rules='Japanese')
