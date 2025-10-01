from scipy.stats import shapiro, ttest_ind, ttest_rel, kruskal, wilcoxon

def shapiro_wilk_test(data):
    """Perform Shapiro-Wilk test for normality."""
    stat, p_value = shapiro(data)
    return p_value > 0.05  # Return True if normal, False otherwise

def independent_t_test(data1, data2, alternative='two-sided'):
    """Perform independent t-test."""
    stat, p_value = ttest_ind(data1, data2, alternative=alternative)
    return stat, p_value

def paired_t_test(data1, data2, alternative='two-sided'):
    """Perform paired t-test."""
    stat, p_value = ttest_rel(data1, data2, alternative=alternative)
    return stat, p_value

def kruskal_wallis_test(data1, data2):
    """Perform Kruskal-Wallis test."""
    stat, p_value = kruskal(data1, data2)
    return stat, p_value

def wilcoxon_signed_rank_test(data1, data2):
    """Perform Wilcoxon signed-rank test."""
    stat, p_value = wilcoxon(data1, data2)
    return stat, p_value
