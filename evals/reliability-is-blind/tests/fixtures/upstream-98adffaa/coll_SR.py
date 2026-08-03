from marketplace import *

name="Coll-SR"

def pick_task_assets(assets, num_assets):
    assert len(assets)>=num_assets
    chosen_assets = []
    for _ in range(num_assets):
        chosen_asset = None
        weights = [asset.stake for asset in assets]

        while chosen_asset in chosen_assets or chosen_asset is None:
            chosen_asset = random.choices(assets, weights=weights, k=1)[0]

        chosen_assets.append(chosen_asset)
    return chosen_assets

# Function to run a single simulation
def run_simulation(faulty_sets, p_fail_distribution):
    
    # Calculate the failure rate target
    failure_rate_target = REWARD_AMOUNT / (REWARD_AMOUNT + SLASH_AMOUNT)
    individual_failure_rate_target = 1 - (1 - failure_rate_target) ** (1 / N_MAX_ASSETS_TASK)

    # Initialize assets and faulty sets
    total_assets = N_ASSETS_INITIAL
    assets = [Asset(i, S0, generate_p_fail(p_fail_distribution)) for i in range(N_ASSETS_INITIAL)]
    all_assets = assets.copy()

    for asset in assets:
        faulty_set = FaultySet([asset], asset.failure_rate)
        asset.failure_rate = faulty_set.p_fail
        faulty_sets.append(faulty_set)

    # Generate faulty combinations for the initial assets
    for asset in assets:
        generate_faulty_combinations(asset, assets, faulty_sets, p_fail_distribution)

    successful_tasks = 0
    failed_tasks = 0
    true_positive = 0
    false_positive = 0
    false_negative = 0

    task_failed_list = []
    removed_assets = []
    system_failure_rates = []
    asset_counts = []
    average_failure_rates = []

    # Task simulation loop
    for task_id in range(1, N_TASKS + 1):
        while len(assets)<N_MIN_ASSETS_TASK:
            add_asset(assets, faulty_sets, p_fail_distribution)
            all_assets.append(assets[-1])
            total_assets += 1
            print("added asset")
        assert len(assets)>=N_MIN_ASSETS_TASK
        # Pick a random subset of assets for the task
        task_assets = pick_task_assets(assets, random.randint(N_MIN_ASSETS_TASK, N_MAX_ASSETS_TASK))
    
        # Check for faulty subsets within the chosen assets
        task_failed = False
        for faulty_set in faulty_sets:
            # Find if faulty set is a subset of task_assets
            if set(faulty_set.assets).issubset(task_assets):
                # Random chance to see if this faulty set triggers a failure
                if random.random() < faulty_set.p_fail:
                    # Task failed, slash all assets involved
                    task_failed = True
                    failed_tasks += 1
                    for asset in task_assets:
                        asset.stake -= SLASH_AMOUNT
                        asset.nb_tasks += 1
                        asset.loss += SLASH_AMOUNT
                        # Cap the stake to min and max values
                        asset.stake = max(min(asset.stake, MAX_REPUTATION), MIN_REPUTATION)
                    break

        if not task_failed:
            # Task succeeded, reward all assets involved
            successful_tasks += 1
            for asset in task_assets:
                asset.stake += REWARD_AMOUNT
                asset.nb_tasks += 1
                # Cap the stake to min and max values
                asset.stake = max(min(asset.stake, MAX_REPUTATION), MIN_REPUTATION)
                asset.reward += REWARD_AMOUNT
        task_failed_list.append(task_failed)

        # Remove assets and corresponding faulty sets with zero or negative stake
        to_remove = [asset for asset in assets if asset.stake <= SLASH_AMOUNT]
        removed_assets.extend(to_remove)
        for asset in to_remove:
            removed_failure_rate = [fs.p_fail for fs in faulty_sets if asset in fs.assets and len(fs.assets) == 1]
            if removed_failure_rate and removed_failure_rate[0] > individual_failure_rate_target:
                true_positive += 1
            else:
                false_positive += 1
            assets.remove(asset)
        # faulty_sets = [fs for fs in faulty_sets if all(asset in assets for asset in fs.assets)]

        # Every few tasks, add a new asset and corresponding faulty sets
        if task_id % NEW_ASSET_INTERVAL == 0 and (N_MAX_ASSETS<=0 or len(assets) < N_MAX_ASSETS):
            add_asset(assets, faulty_sets, p_fail_distribution)
            all_assets.append(assets[-1])
            total_assets += 1
        
        # Track system evolution metrics
        system_failure_rate = failed_tasks / task_id
        average_failure_rate = np.mean([fs.p_fail for fs in faulty_sets])
        
        system_failure_rates.append(system_failure_rate)
        average_failure_rates.append(average_failure_rate)
        asset_counts.append(len(assets))
        print(f"Task {task_id}: System Failure Rate = {system_failure_rate:.4f}; Average Failure Rate = {average_failure_rate:.4f}; Number of assets = {len(assets)}", end='\r')
    print(f"Finished {name} tasks")
    # Calculate precision, accuracy, and recall
    for faulty_set in faulty_sets:
        if len(faulty_set.assets) == 1 and faulty_set.p_fail > individual_failure_rate_target:
            false_negative += 1

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive != 0 else 1
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative != 0 else 1

    return {
        'system_failure_rates': system_failure_rates,
        'average_failure_rates': average_failure_rates,
        'asset_counts': asset_counts,
        'successful_tasks': successful_tasks,
        'task_failed_list': task_failed_list,
        'failed_tasks': failed_tasks,
        'final_number_of_assets': len(assets),
        'precision': precision,
        'recall': recall,
        'assets': assets,
        'removed_assets': removed_assets,
        'all_assets': all_assets
    }
