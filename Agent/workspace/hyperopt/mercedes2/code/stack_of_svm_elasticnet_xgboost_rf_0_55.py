{"metadata":{"kernelspec":{"language":"python","display_name":"Python 3","name":"python3"},"language_info":{"pygments_lexer":"ipython3","nbconvert_exporter":"python","version":"3.6.4","file_extension":".py","codemirror_mode":{"name":"ipython","version":3},"name":"python","mimetype":"text/x-python"},"kaggle":{"accelerator":"none","dataSources":[{"sourceId":6565,"databundleVersionId":44042,"sourceType":"competition"}],"isInternetEnabled":false,"language":"python","sourceType":"script","isGpuEnabled":false}},"nbformat_minor":4,"nbformat":4,"cells":[{"cell_type":"code","source":"# %% [code]\nimport pandas as pd\nimport numpy as np\nfrom sklearn.svm import SVR\nfrom sklearn.ensemble import RandomForestRegressor, ExtraTreesRegressor\nfrom sklearn.decomposition import PCA, FastICA\nfrom sklearn.preprocessing import RobustScaler\nfrom sklearn.pipeline import make_pipeline, Pipeline, _name_estimators\nfrom sklearn.linear_model import ElasticNet, ElasticNetCV\nfrom sklearn.model_selection import cross_val_score, KFold\nfrom sklearn.metrics import r2_score\nfrom sklearn.base import BaseEstimator, TransformerMixin\nimport xgboost as xgb\n\n\ntrain = pd.read_csv('../input/train.csv')\ntest = pd.read_csv('../input/test.csv')\n\ny_train = train['y'].values\ny_mean = np.mean(y_train)\nid_test = test['ID']\n\nnum_train = len(train)\ndf_all = pd.concat([train, test])\ndf_all.drop(['ID', 'y'], axis=1, inplace=True)\n\n# One-hot encoding of categorical/strings\ndf_all = pd.get_dummies(df_all, drop_first=True)\n\ntrain = df_all[:num_train]\ntest = df_all[num_train:]\n\n\nclass AddColumns(BaseEstimator, TransformerMixin):\n    def __init__(self, transform_=None):\n        self.transform_ = transform_\n\n    def fit(self, X, y=None):\n        self.transform_.fit(X, y)\n        return self\n\n    def transform(self, X, y=None):\n        xform_data = self.transform_.transform(X, y)\n        return np.append(X, xform_data, axis=1)\n\n\nclass LogExpPipeline(Pipeline):\n    def fit(self, X, y):\n        super(LogExpPipeline, self).fit(X, np.log1p(y))\n\n    def predict(self, X):\n        return np.expm1(super(LogExpPipeline, self).predict(X))\n\n#\n# Model/pipeline with scaling,pca,svm\n#\nsvm_pipe = LogExpPipeline(_name_estimators([RobustScaler(),\n                                            PCA(),\n                                            SVR(kernel='rbf', C=1.0, epsilon=0.05)]))\n                                            \n# results = cross_val_score(svm_pipe, train, y_train, cv=5, scoring='r2')\n# print(\"SVM score: %.4f (%.4f)\" % (results.mean(), results.std()))\n# exit()\n                                            \n#\n# Model/pipeline with scaling,pca,ElasticNet\n#\nen_pipe = LogExpPipeline(_name_estimators([RobustScaler(),\n                                           PCA(n_components=125),\n                                           ElasticNet(alpha=0.001, l1_ratio=0.1)]))\n\n#\n# XGBoost model\n#\nxgb_model = xgb.sklearn.XGBRegressor(max_depth=4, learning_rate=0.005, subsample=0.921,\n                                     objective='reg:linear', n_estimators=1300, base_score=y_mean)\n                                     \nxgb_pipe = Pipeline(_name_estimators([AddColumns(transform_=PCA(n_components=10)),\n                                      AddColumns(transform_=FastICA(n_components=10, max_iter=500)),\n                                      xgb_model]))\n\n# results = cross_val_score(xgb_model, train, y_train, cv=5, scoring='r2')\n# print(\"XGB score: %.4f (%.4f)\" % (results.mean(), results.std()))\n\n\n#\n# Random Forest\n#\nrf_model = RandomForestRegressor(n_estimators=250, n_jobs=4, min_samples_split=25,\n                                 min_samples_leaf=25, max_depth=3)\n\n# results = cross_val_score(rf_model, train, y_train, cv=5, scoring='r2')\n# print(\"RF score: %.4f (%.4f)\" % (results.mean(), results.std()))\n\n\n#\n# Now the training and stacking part.  In previous version i just tried to train each model and\n# find the best combination, that lead to a horrible score (Overfit?).  Code below does out-of-fold\n# training/predictions and then we combine the final results.\n#\n# Read here for more explanation (This code was borrowed/adapted) :\n#\n\nclass Ensemble(object):\n    def __init__(self, n_splits, stacker, base_models):\n        self.n_splits = n_splits\n        self.stacker = stacker\n        self.base_models = base_models\n\n    def fit_predict(self, X, y, T):\n        X = np.array(X)\n        y = np.array(y)\n        T = np.array(T)\n\n        folds = list(KFold(n_splits=self.n_splits, shuffle=True, random_state=2016).split(X, y))\n\n        S_train = np.zeros((X.shape[0], len(self.base_models)))\n        S_test = np.zeros((T.shape[0], len(self.base_models)))\n        for i, clf in enumerate(self.base_models):\n\n            S_test_i = np.zeros((T.shape[0], self.n_splits))\n\n            for j, (train_idx, test_idx) in enumerate(folds):\n                X_train = X[train_idx]\n                y_train = y[train_idx]\n                X_holdout = X[test_idx]\n                y_holdout = y[test_idx]\n\n                clf.fit(X_train, y_train)\n                y_pred = clf.predict(X_holdout)[:]\n\n                print (\"Model %d fold %d score %f\" % (i, j, r2_score(y_holdout, y_pred)))\n\n                S_train[test_idx, i] = y_pred\n                S_test_i[:, j] = clf.predict(T)[:]\n            S_test[:, i] = S_test_i.mean(axis=1)\n\n        # results = cross_val_score(self.stacker, S_train, y, cv=5, scoring='r2')\n        # print(\"Stacker score: %.4f (%.4f)\" % (results.mean(), results.std()))\n        # exit()\n\n        self.stacker.fit(S_train, y)\n        res = self.stacker.predict(S_test)[:]\n        return res\n\nstack = Ensemble(n_splits=5,\n                 #stacker=ElasticNetCV(l1_ratio=[x/10.0 for x in range(1,10)]),\n                 stacker=ElasticNet(l1_ratio=0.1, alpha=1.4),\n                 base_models=(svm_pipe, en_pipe, xgb_pipe, rf_model))\n\ny_test = stack.fit_predict(train, y_train, test)\n\ndf_sub = pd.DataFrame({'ID': id_test, 'y': y_test})\ndf_sub.to_csv('submission.csv', index=False)","metadata":{"_uuid":"bb411b28-b25b-4c25-b442-da4f8bb88941","_cell_guid":"d1d7489d-9a78-4bee-af52-dabb8f965085","collapsed":false,"jupyter":{"outputs_hidden":false},"trusted":true},"execution_count":null,"outputs":[]}]}