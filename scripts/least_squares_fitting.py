
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import os

df = pd.read_csv("../Traces/SC/demand/CNSW_RefYear_4006_STEP_CHANGE_POE10_OPSO_MODELLING.csv")
dates = pd.date_range("2024-07-01 00:00","2053-06-30 23:30",freq="30min")
x = df.set_index(["Year","Month","Day"]).values.flatten()
tload = pd.DataFrame(data=x,index=dates)
tload.columns = ["load"]

# -------------------------------
# 1. Precompute SSE for segments
# -------------------------------
def precompute_sse(y):
    n = len(y)
    cumsum = np.insert(np.cumsum(y), 0, 0.0)
    cumsum2 = np.insert(np.cumsum(y**2), 0, 0.0)

    def sse(i, j):
        # Segment y[i:j] (0-based, j exclusive)
        length = j - i
        if length == 0:
            return 0
        sum_y = cumsum[j] - cumsum[i]
        sum_y2 = cumsum2[j] - cumsum2[i]
        mean = sum_y / length
        return sum_y2 - 2*mean*sum_y + length*mean**2

    SSE = np.zeros((n, n))
    for i in range(n):
        for j in range(i+1, n+1):
            SSE[i, j-1] = sse(i, j)
    return SSE

# -------------------------------
# 2. Optimal block fitting (DP)
# -------------------------------
def optimal_blocks(y, K):
    n = len(y)
    SSE = precompute_sse(y)

    dp = np.full((K+1, n), np.inf)
    prev = np.zeros((K+1, n), dtype=int)

    # Base case: 1 block
    for t in range(n):
        dp[1, t] = SSE[0, t]

    # DP recursion
    for k in range(2, K+1):
        for t in range(k-1, n):
            best_val = np.inf
            best_s = 0
            for s in range(k-2, t):
                val = dp[k-1, s] + SSE[s+1, t]
                if val < best_val:
                    best_val = val
                    best_s = s
            dp[k, t] = best_val
            prev[k, t] = best_s

    # Traceback
    boundaries = []
    t = n-1
    for k in range(K, 0, -1):
        s = prev[k, t]
        boundaries.append((s+1, t))
        t = s
    boundaries = boundaries[::-1]
    
    boundaries[0] = (0,boundaries[0][1])
    
    # Build compressed series
    block_means = []
    compressed = np.zeros_like(y, dtype=float)
    for (s, e) in boundaries:
        val = y[s:e+1].mean()
        compressed[s:e+1] = val
        block_means.append(val)

    return compressed, boundaries, block_means

# -------------------------------
# 3. Example from CNSW load profile
# -------------------------------
if __name__ == "__main__":
    np.random.seed(0)
    hours = np.arange(336) / 2  # half-hourly timestamps
    i=190
    load = tload.load.values[48*7*i:48*7*(i+1)]

    K = 15
    compressed, boundaries, block_means = optimal_blocks(load, K)

    # Compute snapshot weightings
    block_weights = [(e-s+1)/2 for (s, e) in boundaries]  # hours

    # Error metrics
    mse = np.mean((load - compressed)**2)
    rmse = np.sqrt(mse)
    mae = np.mean(np.abs(load - compressed))

    print("=== Error Metrics ===")
    print(f"MSE:  {mse:.2f}")
    print(f"RMSE: {rmse:.2f}")
    print(f"MAE:  {mae:.2f}\n")

    print("=== Block Summary ===")
    for i, ((s, e), val, w) in enumerate(zip(boundaries, block_means, block_weights), 1):
        print(f"Block {i:2d}: {s:3d}-{e:3d}, mean={val:7.1f} MW, weight={w:4.1f} h")

    print("Blocks Mean",sum(np.array(block_means)*np.array(block_weights))/sum(np.array(block_weights)))
    print("Compressed Mean",np.mean(compressed))

    # Plot
    plt.figure(figsize=(12,5))
    plt.plot(hours, load, label="Original load", alpha=0.6)
    plt.step(hours, compressed, where="post", label=f"{K}-block fit", linewidth=2)
    for (s, e) in boundaries:
        plt.axvline(s/2, color="grey", linestyle="--", alpha=0.3)
    plt.xlabel("Hour of week")
    plt.ylabel("Load (MW)")
    plt.title(f"Optimal {K}-block Least Squares Fit (1 week, 336 half-hours)")
    plt.legend()
    plt.show()


def create_fitted_loads(load_region,load_subtractor):

    no_of_weeks = len(x) // (48*7)
    # no_of_weeks = 2

    K = 15

    fitted = []
    boundariesAll = []
    blockMeans = []

    for week in range(no_of_weeks):

        print(week)
        
        # extra 48 at the last one
        
        if week == 1512:
            load = x[week*336:]
            K=17
            compressed, boundaries, block_means = optimal_blocks(load, K)
        else:
            load = x[week*336:336*(week+1)]

            compressed, boundaries, block_means = optimal_blocks(load, K)

        fitted.append(compressed)
        boundariesAll.append(boundaries)
        blockMeans.append(block_means)

    compressed = np.concatenate([arr for arr in fitted])

    # boundaries = np.array(boundariesAll).reshape(-1, 2)
    boundaries = np.concatenate([np.atleast_2d(b) for b in boundariesAll])

    block_means = np.concatenate([m for m in blockMeans])

    # Compute snapshot weightings
    block_weights = [(e - s + 1) / 2 for (s, e) in boundaries]  # hours


for subr in os.listdir("../Traces/PC/demand/"):

    # if "CNSW" in subr:
    #     continue
    
    print(subr)

    df = pd.read_csv("../Traces/PC/demand/" + subr)
    dates = pd.date_range("2024-07-01 00:00","2053-06-30 23:30",freq="30min")
    x = df.set_index(["Year","Month","Day"]).values.flatten()
    tload = pd.DataFrame(data=x,index=dates)
    tload.columns = ["load"]

    no_of_weeks = len(x) // (48*7)
    # no_of_weeks = 2

    K = 15

    # fitted = []
    boundariesAll = []
    blockMeans = []

    for week in range(no_of_weeks):

        print(week)
        
        # extra 48 at the last one
        
        if week == 1512:
            load = x[week*336:]
            K=17
            _, boundaries, block_means = optimal_blocks(load, K)
        else:
            load = x[week*336:336*(week+1)]

            _, boundaries, block_means = optimal_blocks(load, K)

        # fitted.append(compressed)
        boundariesAll.append(boundaries)
        blockMeans.append(block_means)

    boundaries = np.concatenate([np.atleast_2d(b) for b in boundariesAll])

    block_means = np.concatenate([m for m in blockMeans])

    # Compute snapshot weightings
    block_weights = [(e - s + 1) / 2 for (s, e) in boundaries]  # hours

    n = len(boundaries)
    start_idxs = [
        int(s) + 336 * ((i // 15)-1) if i >= (n - 2) else int(s) + 336 * (i // 15)
        for i, (s, _) in enumerate(boundaries)
    ]

    start_times = dates[start_idxs]

    least_squares = pd.DataFrame(index=start_times, data={
        'weight' : block_weights,
        'load':block_means
    })

    least_squares.index.name = "date"

    least_squares.to_csv(f"../Traces/PC/demand_blocks/15pWk/15_block_{subr}")


# Weighted Least Squares

import numpy as np
import matplotlib.pyplot as plt

def precompute_weighted_sse(y, weights):
    n = len(y)
    cumsum_w = np.insert(np.cumsum(weights), 0, 0.0)
    cumsum_yw = np.insert(np.cumsum(y * weights), 0, 0.0)
    cumsum_y2w = np.insert(np.cumsum((y**2) * weights), 0, 0.0)

    def sse(i, j):
        # Segment y[i:j] (0-based, j exclusive)
        w_sum = cumsum_w[j] - cumsum_w[i]
        if w_sum == 0:
            return 0
        yw_sum = cumsum_yw[j] - cumsum_yw[i]
        y2w_sum = cumsum_y2w[j] - cumsum_y2w[i]
        mean = yw_sum / w_sum
        return y2w_sum - 2 * mean * yw_sum + mean**2 * w_sum

    SSE = np.zeros((n, n))
    for i in range(n):
        for j in range(i+1, n+1):
            SSE[i, j-1] = sse(i, j)
    return SSE

def optimal_blocks_weighted(y, K, weights=None):
    n = len(y)
    if weights is None:
        weights = np.ones_like(y)
    SSE = precompute_weighted_sse(y, weights)

    dp = np.full((K+1, n), np.inf)
    prev = np.zeros((K+1, n), dtype=int)

    # Base case: 1 block
    for t in range(n):
        dp[1, t] = SSE[0, t]

    # DP recursion
    for k in range(2, K+1):
        for t in range(k-1, n):
            best_val = np.inf
            best_s = 0
            for s in range(k-2, t):
                val = dp[k-1, s] + SSE[s+1, t]
                if val < best_val:
                best_val = val
                best_s = s
                dp[k, t] = best_val
                prev[k, t] = best_s

    # Traceback
    boundaries = []
    t = n-1
    for k in range(K, 0, -1):
        s = prev[k, t]
        boundaries.append((s+1, t))
        t = s
        boundaries = boundaries[::-1]

    # Build compressed series
    block_means = []
    compressed = np.zeros_like(y, dtype=float)
    for (s, e) in boundaries:
        w = weights[s:e+1]
        print(w)
        val = np.average(y[s:e+1], weights=w)
        compressed[s:e+1] = val
        block_means.append(val)

    compressed[0] = compressed[1] # Handle first element

    return compressed, boundaries, block_means

# # 48-period block, indices 32-42 (inclusive) have weight 5, others weight 1
weights = [2 if (32 <= i <= 42) or (5 <= i <= 16) else 1 for i in range(48)]
# # weights = [1 for i in range(48)]
# print(weights)


# -------------------------------
# 3. Example with synthetic data
# -------------------------------
if __name__ == "__main__":
    np.random.seed(0)
    hours = np.arange(48) # half-hourly timestamps
    # daily_pattern = (
    # 600 + 200*np.sin(2*np.pi*hours/24) + 50*np.random.randn(len(hours))
    # )
    # load = np.clip(daily_pattern, 300, None)
    i=1690
    load = tload.load.values[48*i:48*(i+1)]

    K = 8
    compressed, boundaries, block_means = optimal_blocks_weighted(load, K,weights=weights)

    # Compute snapshot weightings
    block_weights = [(e-s+1)/2 for (s, e) in boundaries] # hours

    # Error metrics
    mse = np.mean((load - compressed)**2)
    rmse = np.sqrt(mse)
    mae = np.mean(np.abs(load - compressed))

    print("=== Error Metrics ===")
    print(f"MSE: {mse:.2f}")
    print(f"RMSE: {rmse:.2f}")
    print(f"MAE: {mae:.2f}\n")

    print("=== Block Summary ===")
    for i, ((s, e), val, w) in enumerate(zip(boundaries, block_means, block_weights), 1):
        print(f"Block {i:2d}: {s:3d}-{e:3d}, mean={val:7.1f} MW, weight={w:4.1f} h")

    # Plot
    plt.figure(figsize=(12,5))
    plt.plot(hours, load, label="Original load", alpha=0.6)
    plt.step(hours, compressed, where="post", label=f"{K}-block fit", linewidth=2)
    for (s, e) in boundaries:
        plt.axvline(s, color="grey", linestyle="--", alpha=0.3)
    plt.xlabel("Hour of week")
    plt.ylabel("Load (MW)")
    plt.title(f"Optimal {K}-block Least Squares Fit (1 week, 336 half-hours)")
    plt.legend()
    plt.show()
