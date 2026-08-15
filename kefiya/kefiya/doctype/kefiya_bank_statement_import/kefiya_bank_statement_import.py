import frappe
from frappe.model.document import Document
import csv
import os
from frappe.utils.file_manager import get_file_path
from datetime import datetime
from frappe import _
import chardet
import locale

from kefiya.utils import statement_import

class KefiyaBankStatementImport(Document):

	@frappe.whitelist()
	def plan_import(self, file_url, bank_account):
		"""Report what an import would do, without writing anything.

		A bulk insert of bookings is the kind of write that should be looked at
		before it happens, not explained afterwards. The plan names the format
		that was recognised, shows the first few bookings as they were
		understood -- above all which way round the signs came out, which is
		where a card statement goes wrong silently -- and counts how many rows
		are already present.
		"""
		frappe.has_permission(
			"Kefiya Bank Statement Import", ptype="read", doc=self, throw=True)
		return statement_import.plan(file_url, bank_account)

	@frappe.whitelist()
	def start_import(self, file_url, bank_account, company):
		# Permission gate: a whitelisted document method is callable by anyone
		# who may read the document; importing creates Bank Transactions.
		frappe.has_permission(
			"Kefiya Bank Statement Import", ptype="write", doc=self, throw=True)

		# The reader that maps columns by name handles every format it knows,
		# including the card statements that have no IBAN column at all. Only
		# when it recognises nothing does the original positional reader take
		# over, so files that imported before still import.
		plan = statement_import.plan(file_url, bank_account)
		if plan.get("profile"):
			return self.import_planned(plan, bank_account, company)

		file_path = self.get_file_from_url(file_url)
		# Detect encoding
		with open(file_path, 'rb') as f:
			rawdata = f.read()
			result = chardet.detect(rawdata)
			encoding = result['encoding']

		total_rows = sum(1 for _ in open(file_path, mode='r', encoding=encoding))-7
		self.db_set('payload_count', total_rows)

		try:
			with open(file_path, mode='r', encoding=encoding, errors='replace') as csvfile:
				csv_reader = csv.reader(csvfile)
                # Skip header (the first 7 rows)
				for _ in range(7):
					next(csv_reader)

				frappe.publish_progress(0, title='Importing Bank Transaction', description='Starting import...')
                
				for index, row in enumerate(csv_reader):
					if encoding == 'utf-8':
						self.create_new_doc_utf8(row, bank_account, company, index, total_rows)
					elif encoding == 'ISO-8859-1':
						self.create_new_doc_iso(row, bank_account, company, index, total_rows)
					else:
						frappe.msgprint("Unsupported file format. Only utf-8 and ISO-8859-1 formats are supported currently.")
						
						self.update_status('Error')
						return

					index += 1
					progress = int((index / total_rows) * 100)
					frappe.publish_progress(progress, title='Importing Bank Transaction', description=f'Processing row {index}/{total_rows}')

		except Exception as e:
			frappe.msgprint(f'Error during import: {e}')
			self.update_status('Error')


	def import_planned(self, plan, bank_account, company):
		"""Book the entries a plan already read, counted and de-duplicated.

		plan() has done the reading, so nothing here re-parses a value: a row
		that books must be the row the plan showed. Each booking carries the
		reference plan() gave it, which is what makes importing the same file
		twice harmless -- the old import had no such check and simply created
		every booking again.
		"""
		entries = plan.get("entries") or []
		self.db_set('payload_count', plan.get("total") or 0)

		created = 0
		for index, entry in enumerate(entries):
			try:
				booking = frappe.new_doc("Bank Transaction")
				booking.update({
					"date": str(entry["date"]),
					"deposit": entry["amount"] if entry["amount"] > 0 else 0,
					"withdrawal": -entry["amount"] if entry["amount"] < 0 else 0,
					"bank_account": bank_account,
					"company": company,
					"description": " ".join(
						x for x in (entry.get("counterparty"),
									entry.get("description")) if x),
					"bank_party_iban": entry.get("iban"),
					"bank_party_name": entry.get("counterparty") or None,
					"reference_number": entry["reference_number"],
					"allocated_amount": 0,
					"unallocated_amount": abs(entry["amount"]),
					"status": "Unreconciled",
				})
				if entry.get("iban"):
					party, party_type = get_bank_account_data(entry["iban"])
					booking.party, booking.party_type = party, party_type
				booking.insert()
				created += 1
			except Exception as e:
				frappe.msgprint(
					f'Error creating document for row {index + 1}: {e}')

			frappe.publish_progress(
				int(((index + 1) / max(len(entries), 1)) * 100),
				title='Importing Bank Transaction',
				description=f'Processing row {index + 1}/{len(entries)}')

		self.db_set('imported_records', created)
		self.update_status('Success' if created == len(entries)
						   else 'Partial Success')

		if self.submit_after_success:
			# Deliberately not submitted from here. Submitting a booking is an
			# approval, and an approval is given at the document, not by a
			# checkbox on an import that ran unattended. Said out loud rather
			# than ignored, so the setting does not look as if it worked.
			frappe.msgprint(_(
				"{0} bookings were created as drafts. Submitting them is left"
				" to the Bank Transaction list."
			).format(created))
		return {
			"created": created,
			"duplicates": plan.get("duplicates") or 0,
			"unreadable": plan.get("unreadable") or 0,
			"profile": plan.get("label"),
		}

	def update_status(self, status):
		self.db_set('status', status)
		frappe.publish_realtime('update_import_status', {'docname': self.name, 'status': status}, user=frappe.session.user)

	def get_file_from_url(self, file_url):
		
		base = frappe.local.site_path
		file_path = base + file_url

		if not os.path.exists(file_path):
			frappe.throw(_('File not found: {0}').format(file_path))
		
		return file_path

	# utf-8
	def create_new_doc_utf8(self, row_data, bank_account, company, index, total_rows):
        # This function create a new document from a csv row
		try:
			bank_transaction = frappe.new_doc("Bank Transaction")
			date =  datetime.strptime( row_data[0], '%d.%m.%Y')
			description = row_data[4]
			bank_party_iban = row_data[5]
			bank_party_name = row_data[3]
			party, party_type = get_bank_account_data(bank_party_iban)
			deposit, withdrawal = self.format_amount_utf8(row_data[7])

			# Without this the second import of a file created every booking a
			# second time. The reference is built the same way the fetched
			# bookings build theirs, so a row imported here and later fetched
			# from the bank is recognised as one booking, not two.
			reference = statement_import.reference_number(bank_account, {
				"date": date.strftime('%Y-%m-%d'),
				"amount": deposit - withdrawal,
				"counterparty": bank_party_name,
				"description": description,
			})
			# Skipped, not returned early: the run's completion is decided at
			# the end of this method, and a duplicate as the last row of the
			# file would otherwise leave the import stuck on "Not Started".
			if not frappe.db.exists("Bank Transaction",
									{"reference_number": reference}):
				bank_transaction.update({
					"reference_number": reference,
					"date": date.strftime('%Y-%m-%d'),
					"deposit": deposit,
					"withdrawal": withdrawal,
					"bank_account": bank_account,
					"company": company,
					"description": description,
					'bank_party_iban': bank_party_iban,
					'allocated_amount': 0,
					'unallocated_amount': abs(withdrawal - deposit),
					'party': party,
					'party_type': party_type,
					"bank_party_name": bank_party_name
				})

				bank_transaction.insert()
				if self.submit_after_success:
					bank_transaction.submit()

			if index+1==total_rows and self.status=='Not Started':
				self.db_set('imported_records', index+1)
				self.update_status('Success')

		except Exception as e:
			frappe.msgprint(f'Error creating document for row: {row_data} - {e}')
			self.db_set('imported_records', index)
			self.update_status('Partial Success')

	def format_amount_utf8(self, amount):
		deposit, withdrawal = 0,0

		if '.' in amount:
			amount = amount.replace('.', '')
		if ',' in amount:
			amount = amount.replace(',', '.')

		amount = float(amount)
		if amount >= 0:
			deposit = amount
		else:
			withdrawal = abs(amount)

		return [deposit, withdrawal]


	# ISO-8859-1
	def create_new_doc_iso(self, row_data, bank_account, company, index, total_rows):
        # This function create a new document from a csv row
		
		row_data = ''.join(row_data)
		row_data = row_data.split(';')
		try:
			bank_transaction = frappe.new_doc("Bank Transaction")
			date =  datetime.strptime( row_data[0], '%d.%m.%Y')
			description = row_data[4].replace('"', '')
			bank_party_iban = row_data[5].replace('"', '')
			bank_party_name = row_data[3].replace('"', '')
			party, party_type = get_bank_account_data(bank_party_iban)
			deposit, withdrawal = self.format_amount_iso(row_data[7])

			# Same guard as the utf-8 path: a repeated import must not create
			# the same booking again.
			reference = statement_import.reference_number(bank_account, {
				"date": date.strftime('%Y-%m-%d'),
				"amount": deposit - withdrawal,
				"counterparty": bank_party_name,
				"description": description,
			})
			# Skipped, not returned early: see the utf-8 path -- a duplicate as
			# the last row would otherwise leave the import on "Not Started".
			if not frappe.db.exists("Bank Transaction",
									{"reference_number": reference}):
				bank_transaction.update({
					"reference_number": reference,
					"date": date.strftime('%Y-%m-%d'),
					"deposit": deposit,
					"withdrawal": withdrawal,
					"bank_account": bank_account,
					"company": company,
					"description": description,
					'bank_party_iban': bank_party_iban,
					'allocated_amount': 0,
					'unallocated_amount': abs(withdrawal - deposit),
					'party': party,
					'party_type': party_type,
					"bank_party_name":  bank_party_name
				})

				bank_transaction.insert()
				if self.submit_after_success:
					bank_transaction.submit()

			if index+1==total_rows and self.status=='Not Started':
				self.db_set('imported_records', index+1)
				self.update_status('Success')
		except Exception as e:
			frappe.msgprint(f'Error creating document for row: {row_data} - {e}')
			
			self.db_set('imported_records', index)
			self.update_status('Partial Success')
	
	def format_amount_iso(self, amount):
		deposit, withdrawal = 0,0

		if '"' in amount:
			amount = amount.replace('"', '')

		if ',' in amount and '.' in amount:
			amount = amount.replace('.', '').replace(',', '.')
		elif ',' in amount:
			amount = amount.replace(',', '.')
		elif '.' in amount:
			amount = amount.replace('.', '')
			integer_part = amount[:-2]
			decimal_part = amount[-2:]
			amount = integer_part + '.' + decimal_part
		else:
			try:
				integer_part = amount[:-2]
				decimal_part = amount[-2:]
				amount = integer_part + '.' + decimal_part
			except Exception as e:
				# `row_data` does not exist here -- this method only receives
				# the amount. Referencing it raised NameError from inside the
				# except block, replacing the intended message with a crash.
				frappe.msgprint(f'currency formatting not supported for amount: {amount} - {e}')

		amount = float(amount)
		if amount >= 0:
			deposit = amount
		else:
			withdrawal = abs(amount)

		return [deposit, withdrawal]
	
def get_bank_account_data(IBAN):
	party, party_type = '', ''
	bank_account_exists = frappe.db.exists('Bank Account', {'iban': IBAN})
	
	if bank_account_exists:
		bank_account_doc = frappe.get_doc('Bank Account', {'iban': IBAN})
		party = bank_account_doc.party
		party_type = bank_account_doc.party_type

	return [party, party_type]