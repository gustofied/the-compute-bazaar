import numpy as np
import random
import matplotlib.pyplot as plt
import sys

N_ASSETS_INITIAL = 100          # N_{a}: Initial number of assets
N_MAX_ASSETS = N_ASSETS_INITIAL # Maximum number of assets
N_MIN_ASSETS_TASK = 4           # Minimum number of assets for each task
N_MAX_ASSETS_TASK = 4           # Maximum number of assets for each task

S0 = 10                         # S_{0}: Initial stake backing each asset
N_TASKS = 10000                 # N_{t}: Number of tasks to simulate
SLASH_AMOUNT = 1                # P: Amount slashed for failed tasks
TARGET_TASK_FAILURE_RATE = 0.05 # F_{t}^{target}: Target failure rate for each task
REWARD_AMOUNT = TARGET_TASK_FAILURE_RATE/(1-TARGET_TASK_FAILURE_RATE) # R: Reward for successful tasks

MIN_REPUTATION = S0/1000
MAX_REPUTATION = S0

NEW_ASSET_INTERVAL = 500        # T: Period between new asset additions (in tasks)
NEW_ASSET_FAULTY_COMBOS = 0     # Number of faulty combinations per new asset
N_SIM_RUNS = 100                 # Number of simulations
N_FAIL_SAMPLES=100000

ALPHA=0.1

# Display
WINDOW_SIZE = 500

FIG_DIR="out/fig"
DATA_DIR="out/data"

N_JOBS = int(sys.argv[1]) if len(sys.argv) > 1 else 1

params = {'text.usetex' : True,
          'font.size' : 10,
            'font.family' : 'serif',
            'font.serif' : 'Computer Modern Roman',
          }
plt.rcParams.update(params) 

# Function to pad a list with zeros up to a target length
def pad_list_with_zeros(lst, target_length):
    return lst + [0] * (target_length - len(lst))

# Function extend list to desired length by repeatinig the last element
def extend_list(lst, target_length):
    return lst + [lst[-1]] * (target_length - len(lst))

def moving_average(a, n=3):
    ret = np.cumsum(a, dtype=float)
    ret[n:] = ret[n:] - ret[:-n]
    ret[:n-1] = ret[:n-1] / np.arange(1, n)
    ret[n - 1:]= ret[n - 1:] / n
    return ret

# Initialize assets and faulty sets
class Asset:
    def __init__(self, id, stake, failure_rate):
        self.id = id
        self.stake = stake
        self.failure_rate = failure_rate
        self.loss = 0
        self.reward = 0
        self.nb_tasks = 0

class FaultySet:
    def __init__(self, assets, p_fail):
        self.assets = assets
        self.p_fail = p_fail

# Add an asset with a faulty set
def add_asset(assets, faulty_sets, p_fail_distribution):
    # Add a new asset
    new_asset = Asset(len(assets), S0, generate_p_fail(p_fail_distribution))
    assets.append(new_asset)

    # Generate a faulty set for the new asset
    faulty_set = FaultySet([new_asset], new_asset.failure_rate)
    faulty_sets.append(faulty_set)
    new_asset.failure_rate = faulty_set.p_fail
    
    # Generate faulty combinations sets for the new asset
    generate_faulty_combinations(new_asset, assets, faulty_sets, p_fail_distribution)

# Generate initial faulty sets
def generate_faulty_combinations(asset, assets, faulty_sets, p_fail_distribution):
    for _ in range(NEW_ASSET_FAULTY_COMBOS):
        subset_size = random.randint(N_MIN_ASSETS_TASK, N_MAX_ASSETS_TASK-1)
        subset = random.sample(assets, subset_size)
        subset.append(asset)
        p_fail = generate_p_fail(p_fail_distribution)
        faulty_sets.append(FaultySet(subset, p_fail))

# Generate p_fail based on long tail distribution
def generate_p_fail(p_fail_distribution):
    p_fail = np.random.choice(p_fail_distribution)
    while p_fail < 0 or p_fail > 1:
        p_fail = np.random.choice(p_fail_distribution)
    # return max(0, min(1, np.random.choice(p_fail_distribution)))
    return p_fail

# Bins setup for failure rates
def get_failure_rate_bin(p_fail, bin_size=0.05):
    return round(min(max(p_fail, 0), 1) // bin_size * bin_size, 2)

# Function to compute average reward and loss per failure rate bin
def compute_average_reward_and_loss(assets, removed_assets, faulty_sets):
    reward_bins = {round(i * 0.05, 2): [] for i in range(20)}  # Bins of 0.05
    loss_bins = {round(i * 0.05, 2): [] for i in range(20)}    # Bins of 0.05

    # Iterate through all assets
    for asset in assets:
        if asset.nb_tasks == 0:
            continue
        
        bin_key = get_failure_rate_bin(asset.failure_rate)
        
        # Add asset's reward and loss to the corresponding bin
        reward_bins[bin_key].append(asset.reward / asset.nb_tasks)
        loss_bins[bin_key].append(asset.loss / asset.nb_tasks)

    for asset in removed_assets:
        if asset.nb_tasks == 0:
            continue

        bin_key = get_failure_rate_bin(asset.failure_rate)
        
        # Add asset's reward and loss to the corresponding bin
        reward_bins[bin_key].append(asset.reward / asset.nb_tasks)
        loss_bins[bin_key].append(asset.loss / asset.nb_tasks)

    # Compute the averages for each bin
    average_rewards_per_bin = {bin_key: np.mean(values) if values else 0 for bin_key, values in reward_bins.items()}
    average_losses_per_bin = {bin_key: np.mean(values) if values else 0 for bin_key, values in loss_bins.items()}

    return average_rewards_per_bin, average_losses_per_bin
