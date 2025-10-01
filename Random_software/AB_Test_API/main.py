from flask import Flask, request, jsonify
from stat_tests import (
    shapiro_wilk_test,
    independent_t_test,
    paired_t_test,
    kruskal_wallis_test,
    wilcoxon_signed_rank_test,
)
from data_utils import sample_data, is_paired

app = Flask(__name__)

def perform_ab_test(data1, data2, alpha, paired=False):
    """Perform A/B testing based on the given data and parameters."""
    # Step 1: Check data size and perform Shapiro-Wilk test
    data1_sampled = sample_data(data1) if len(data1) > 1000 else data1
    data2_sampled = sample_data(data2) if len(data2) > 1000 else data2
    is_normal1 = shapiro_wilk_test(data1_sampled)
    is_normal2 = shapiro_wilk_test(data2_sampled)

    # Step 2: Determine the best test
    if is_normal1 and is_normal2:
        if not is_paired(data1, data2, paired):
            test_name = "Independent t-test (two-tailed)"
            stat, p_value = independent_t_test(data1, data2, alternative='two-sided')
            if p_value < alpha:
                # Perform right-tailed and left-tailed t-tests to determine which dataset is greater
                stat1, p_value1 = independent_t_test(data1, data2, alternative='greater')
                stat2, p_value2 = independent_t_test(data2, data1, alternative='greater')
                if p_value1 < alpha:
                    test_name = "Independent t-test (right-tailed)"
                    conclusion = "sample_data1 is greater than sample_data2"
                    p_value = p_value1
                elif p_value2 < alpha:
                    test_name = "Independent t-test (left-tailed)"
                    conclusion = "sample_data2 is greater than sample_data1"
                    p_value = p_value2
                else:
                    conclusion = "datasets are statistically different"
            else:
                conclusion = "datasets are statistically same"
        else:
            test_name = "Paired t-test (two-tailed)"
            stat, p_value = paired_t_test(data1, data2, alternative='two-sided')
            if p_value < alpha:
                # Perform right-tailed and left-tailed paired t-tests to determine which dataset is greater
                stat1, p_value1 = paired_t_test(data1, data2, alternative='greater')
                stat2, p_value2 = paired_t_test(data2, data1, alternative='greater')
                if p_value1 < alpha:
                    test_name = "Paired t-test (right-tailed)"
                    conclusion = "sample_data1 is greater than sample_data2"
                    p_value = p_value1
                elif p_value2 < alpha:
                    test_name = "Paired t-test (left-tailed)"
                    conclusion = "sample_data2 is greater than sample_data1"
                    p_value = p_value2
                else:
                    conclusion = "datasets are statistically different"
            else:
                conclusion = "datasets are statistically same"
    else:
        if not is_paired(data1, data2, paired):
            test_name = "Kruskal-Wallis test"
            stat, p_value = kruskal_wallis_test(data1, data2)
            conclusion = "datasets are statistically different" if p_value < alpha else "datasets are statistically same"
        else:
            test_name = "Wilcoxon signed-rank test"
            stat, p_value = wilcoxon_signed_rank_test(data1, data2)
            conclusion = "datasets are statistically different" if p_value < alpha else "datasets are statistically same"

    # Step 3: Return results
    return {
        "test_name": test_name,
        "test_statistic": stat,
        "p_value": p_value,
        "alpha": alpha,
        "conclusion": conclusion,
    }

@app.route('/ab-test', methods=['POST'])
def ab_test_api():
    """API endpoint for A/B testing."""
    # Get data from the request
    data = request.json
    data1 = data['data1']
    data2 = data['data2']
    alpha = data.get('alpha', 0.05)  # Default alpha is 0.05
    paired = data.get('paired', False)  # Default is unpaired

    # Perform A/B test
    result = perform_ab_test(data1, data2, alpha, paired)

    # Return the result as JSON
    return jsonify(result)

# Run the API
if __name__ == '__main__':
    app.run(debug=True)
