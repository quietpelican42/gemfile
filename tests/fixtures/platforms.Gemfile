platforms :jruby do
  gem 'jruby-openssl'
end
platform :mri, :mingw do
  gem 'sqlite3'
  platforms :x64_mingw do
    gem 'nested-platform'
  end
end
gem 'one', platform: :ruby_25
gem 'many', platforms: [:mswin, :mswin64]
platforms :ruby do
  gem 'both-kinds', platforms: :jruby
end
