1. Copy contract_offers.py and install_contract_offers.py into the same folder as app.py.
2. Stop Flask.
3. Run: python install_contract_offers.py
4. Start Flask with: python -c "import app; app.app.run(host='127.0.0.1',port=5001,debug=False,use_reloader=False)"
5. Manager page: http://127.0.0.1:5001/manager/contracts/offers
6. Admin page:   http://127.0.0.1:5001/admin/contracts/offers
7. Player page:  http://127.0.0.1:5001/contract-offers
The patch creates contract_offers automatically and keeps the existing contracts/transfers data.
